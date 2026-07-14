"""Faz 1 — Tool Executor.

Ajanların dosya sistemi ve kabukla güvenli etkileşim katmanı:

- ``read_file`` / ``write_file`` / ``run_shell`` araçları
- Path doğrulama: tüm dosya işlemleri workspace köküne hapsedilir
  (mutlak path ve ``..`` ile dışarı çıkma girişimleri reddedilir)
- ``write_file`` her yazmada unified diff üretir (değişiklik izlenebilirliği)
- ``run_shell`` yerelde veya Docker sandbox içinde çalışabilir

Araç hataları exception yerine ``ToolSonucu(ok=False, ...)`` olarak döner;
böylece hata metni ``tool_result`` içinde modele geri beslenebilir.
"""

from __future__ import annotations

import difflib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Sınırlar
MAX_OKUMA_BOYUTU = 256 * 1024  # bayt; daha büyük dosyalar kesilerek okunur
MAX_CIKTI_UZUNLUGU = 32_000  # karakter; shell çıktısı bundan uzunsa kesilir
MAX_LISTE_DOSYASI = 500  # list_files en çok bu kadar dosya gösterir
VARSAYILAN_ZAMAN_ASIMI_SN = 30.0

# list_files'ın atladığı klasörler (üretilen/araç çıktısı içerikler)
GIZLENEN_KLASORLER = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".state",
    ".next",
}

# Anthropic Messages API biçiminde araç tanımları (ajan isteklerine eklenecek)
TOOL_TANIMLARI = [
    {
        "name": "read_file",
        "description": "Workspace içindeki bir dosyanın içeriğini okur.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace köküne göreli dosya yolu",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Workspace içindeki bir dosyaya içerik yazar (yoksa oluşturur, "
            "ara klasörler dahil). Yapılan değişikliğin diff'ini döndürür."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace köküne göreli dosya yolu",
                },
                "content": {
                    "type": "string",
                    "description": "Dosyanın yeni içeriğinin tamamı",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": (
            "Workspace'teki dosyaları (alt klasörler dahil) boyutlarıyla listeler. "
            "Hangi dosyaların var olduğunu görmek için önce bunu kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Listelenecek klasör (boşsa workspace kökü)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "run_shell",
        "description": (
            "Workspace kökünde bir kabuk komutu çalıştırır; çıkış kodu, "
            "stdout ve stderr döndürür."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Çalıştırılacak kabuk komutu",
                },
                "timeout": {
                    "type": "number",
                    "description": "Saniye cinsinden zaman aşımı (varsayılan 30)",
                },
            },
            "required": ["command"],
        },
    },
]


@dataclass
class ToolSonucu:
    """Bir araç çağrısının sonucu; ``cikti`` modele tool_result olarak döner."""

    ok: bool
    cikti: str


def _kes(metin: str, sinir: int = MAX_CIKTI_UZUNLUGU) -> str:
    """Metni sinira indirger; kesildiyse sona not düşer."""
    if len(metin) <= sinir:
        return metin
    return metin[:sinir] + f"\n... [çıktı {len(metin)} karakterdi, kesildi]"


class LocalShellRunner:
    """Komutları doğrudan yerel kabukta, workspace kökünde çalıştırır."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    def calistir(self, komut: str, zaman_asimi: float) -> subprocess.CompletedProcess:
        return subprocess.run(
            komut,
            shell=True,
            cwd=self._workspace,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=zaman_asimi,
        )


class DockerShellRunner:
    """Komutları ağa kapalı bir Docker konteynerinde çalıştırır (sandbox).

    Workspace, konteynere /workspace olarak bağlanır; komutlar orada koşar.
    Docker daemon'ın çalışıyor olması gerekir.
    """

    def __init__(self, workspace: Path, image: str = "python:3.12-slim"):
        self._workspace = workspace
        self._image = image

    def calistir(self, komut: str, zaman_asimi: float) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "-v",
                f"{self._workspace}:/workspace",
                "-w",
                "/workspace",
                self._image,
                "sh",
                "-lc",
                komut,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=zaman_asimi,
        )


class ToolExecutor:
    """read_file / write_file / run_shell araçlarını workspace'e hapsederek yürütür."""

    def __init__(self, workspace: Path | str, shell_runner=None):
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace bir klasör değil: {self.workspace}")
        self._shell = shell_runner or LocalShellRunner(self.workspace)

    # --- Path doğrulama ---

    def _coz(self, path: str) -> Path:
        """Göreli yolu workspace içinde mutlak yola çevirir.

        Workspace dışına çıkan her yol (mutlak yol, ``..`` dizileri,
        symlink üzerinden kaçış) ValueError ile reddedilir.
        """
        if not path or not path.strip():
            raise ValueError("path boş olamaz")
        tam = (self.workspace / path).resolve()
        if tam != self.workspace and not tam.is_relative_to(self.workspace):
            raise ValueError(f"path workspace dışına çıkıyor: {path!r}")
        return tam

    # --- Araçlar ---

    def dosya_var_mi(self, path: str) -> bool:
        """Yol workspace içinde var olan bir dosyaya mı işaret ediyor?"""
        try:
            return self._coz(path).is_file()
        except ValueError:
            return False

    def list_files(self, path: str = ".") -> ToolSonucu:
        try:
            tam = self._coz(path or ".")
        except ValueError as e:
            return ToolSonucu(False, f"HATA: {e}")
        if not tam.is_dir():
            return ToolSonucu(False, f"HATA: klasör bulunamadı: {path!r}")

        satirlar: list[str] = []
        for kok, klasorler, dosyalar in os.walk(tam):
            klasorler[:] = sorted(k for k in klasorler if k not in GIZLENEN_KLASORLER)
            for ad in sorted(dosyalar):
                p = Path(kok) / ad
                gorel = p.relative_to(self.workspace).as_posix()
                satirlar.append(f"{gorel} ({p.stat().st_size} B)")
                if len(satirlar) >= MAX_LISTE_DOSYASI:
                    satirlar.append(f"... [{MAX_LISTE_DOSYASI} dosya sınırına ulaşıldı]")
                    return ToolSonucu(True, "\n".join(satirlar))
        if not satirlar:
            return ToolSonucu(True, "(klasör boş)")
        return ToolSonucu(True, "\n".join(satirlar))

    def read_file(self, path: str) -> ToolSonucu:
        try:
            tam = self._coz(path)
        except ValueError as e:
            return ToolSonucu(False, f"HATA: {e}")
        if not tam.is_file():
            return ToolSonucu(False, f"HATA: dosya bulunamadı: {path!r}")

        boyut = tam.stat().st_size
        icerik = tam.read_bytes()[:MAX_OKUMA_BOYUTU].decode("utf-8", errors="replace")
        if boyut > MAX_OKUMA_BOYUTU:
            icerik += f"\n... [dosya {boyut} bayt, ilk {MAX_OKUMA_BOYUTU} bayt gösterildi]"
        return ToolSonucu(True, icerik)

    def write_file(self, path: str, content: str) -> ToolSonucu:
        try:
            tam = self._coz(path)
        except ValueError as e:
            return ToolSonucu(False, f"HATA: {e}")
        if tam == self.workspace or tam.is_dir():
            return ToolSonucu(False, f"HATA: {path!r} bir klasör, dosya değil")

        eski = ""
        yeni_dosya = not tam.exists()
        if not yeni_dosya:
            eski = tam.read_text(encoding="utf-8", errors="replace")

        tam.parent.mkdir(parents=True, exist_ok=True)
        tam.write_text(content, encoding="utf-8", newline="\n")

        diff = "".join(
            difflib.unified_diff(
                eski.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile="/dev/null" if yeni_dosya else f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        etiket = "oluşturuldu" if yeni_dosya else "güncellendi"
        return ToolSonucu(True, f"{path} {etiket}.\n\n{_kes(diff)}")

    def run_shell(self, command: str, timeout: float | None = None) -> ToolSonucu:
        if not command or not command.strip():
            return ToolSonucu(False, "HATA: command boş olamaz")
        if "\n" in command.strip():
            # Windows cmd çok satırlı komutu sessizce bozuyor; modeli sağlam yola it
            return ToolSonucu(
                False,
                "HATA: çok satırlı komut desteklenmiyor. Çok satırlı kod çalıştırmak "
                "için önce write_file ile bir script dosyası yaz, sonra onu tek "
                "satırlık komutla çalıştır (örn. 'python script.py').",
            )
        zaman_asimi = timeout if timeout and timeout > 0 else VARSAYILAN_ZAMAN_ASIMI_SN
        try:
            sonuc = self._shell.calistir(command, zaman_asimi)
        except subprocess.TimeoutExpired:
            return ToolSonucu(
                False, f"HATA: komut {zaman_asimi:.0f} saniyede tamamlanmadı (zaman aşımı)"
            )
        except FileNotFoundError as e:
            # Örn. Docker kurulu değilse
            return ToolSonucu(False, f"HATA: çalıştırıcı bulunamadı: {e}")

        parcalar = [f"çıkış kodu: {sonuc.returncode}"]
        if sonuc.stdout:
            parcalar.append(f"stdout:\n{sonuc.stdout.rstrip()}")
        if sonuc.stderr:
            parcalar.append(f"stderr:\n{sonuc.stderr.rstrip()}")
        return ToolSonucu(sonuc.returncode == 0, _kes("\n".join(parcalar)))

    # --- Dispatcher ---

    def calistir(self, ad: str, girdi: dict) -> ToolSonucu:
        """Araç adını ve girdisini alıp ilgili aracı çağırır (ajan döngüsü girişi)."""
        if ad == "list_files":
            return self.list_files(girdi.get("path") or ".")
        if ad == "read_file":
            return self.read_file(girdi.get("path", ""))
        if ad == "write_file":
            return self.write_file(girdi.get("path", ""), girdi.get("content", ""))
        if ad == "run_shell":
            return self.run_shell(girdi.get("command", ""), girdi.get("timeout"))
        return ToolSonucu(False, f"HATA: bilinmeyen araç: {ad!r}")
