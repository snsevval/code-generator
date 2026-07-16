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
import re
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
    ".kontrol",  # check_page ekran görüntüleri
    ".sunucu",  # arka plan sunucu logları
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
        "name": "edit_file",
        "description": (
            "Bir dosyada küçük değişiklik yapar: eski_metni yeni_metinle değiştirir. "
            "BÜYÜK dosyalarda write_file yerine BUNU kullan (tüm dosyayı yeniden "
            "yazma). eski_metin dosyada birebir ve TEK bir yerde geçmeli."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Düzenlenecek dosyanın yolu"},
                "eski_metin": {
                    "type": "string",
                    "description": "Değiştirilecek mevcut metin (birebir, benzersiz)",
                },
                "yeni_metin": {"type": "string", "description": "Yerine yazılacak metin"},
            },
            "required": ["path", "eski_metin", "yeni_metin"],
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
        "name": "search_files",
        "description": (
            "Workspace'te içeriğe göre arama yapar; sorguya en ilgili dosyaları "
            "skorlarıyla listeler. Hangi dosyanın işinle ilgili olduğundan emin "
            "değilsen read_file'dan önce bunu kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Aranan kavram/işlev (örn. 'not silme fonksiyonu')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "start_server",
        "description": (
            "Bitmeyen bir sunucu sürecini (npm run dev, uvicorn, python -m "
            "http.server vb.) arka planda başlatır ve port dinlemeye başlayınca "
            "döner. Canlı doğrulama için (React/Next dev sunucusu, backend API) "
            "kullan; sonra check_page http://localhost:<port> ile aç. run_shell "
            "yerine BUNU kullan — run_shell bitmeyen süreçte asılır. "
            "Bağımlılık kurmak (npm install/pip install) gerekiyorsa ÖNCE run_shell "
            "ile timeout=600 vererek kur."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Sunucuyu başlatan komut"},
                "port": {"type": "number", "description": "Sunucunun dinleyeceği port"},
            },
            "required": ["command", "port"],
        },
    },
    {
        "name": "stop_server",
        "description": "start_server ile başlatılan sunucuyu durdurur.",
        "input_schema": {
            "type": "object",
            "properties": {"port": {"type": "number", "description": "Durdurulacak port"}},
            "required": ["port"],
        },
    },
    {
        "name": "server_log",
        "description": "Çalışan bir sunucunun son loglarını gösterir (hata ayıklama).",
        "input_schema": {
            "type": "object",
            "properties": {"port": {"type": "number", "description": "Sunucunun portu"}},
            "required": ["port"],
        },
    },
    {
        "name": "check_page",
        "description": (
            "Bir HTML dosyasını headless tarayıcıda açar: sayfa başlığını, konsol "
            "hatalarını ve görsel kalite analizini döndürür, ekran görüntüsü alır. "
            "HTML/arayüz dosyası ürettiysen veya doğruluyorsan mutlaka kullan. "
            "Vite/Next gibi dev-server projelerinde dosya yolu VERME — önce "
            "start_server ile sunucuyu başlat, sonra http://localhost:<port> ver "
            "(dosya yolu file:// ile açılır; modüller yüklenmez, hatalar gizlenir)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Açılacak HTML dosyasının göreli yolu",
                }
            },
            "required": ["path"],
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
        self._sunucu_yoneticisi = None  # tembel: yalnızca start_server çağrılırsa kurulur

    @property
    def sunucu_yoneticisi(self):
        if self._sunucu_yoneticisi is None:
            from orchestrator.sunucu import SunucuYoneticisi

            self._sunucu_yoneticisi = SunucuYoneticisi(self.workspace)
        return self._sunucu_yoneticisi

    def temizle(self) -> None:
        """Görev sonu: açık arka plan sunucularını kapatır (sızıntı önleme)."""
        if self._sunucu_yoneticisi is not None:
            self._sunucu_yoneticisi.hepsini_durdur()

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

    def search_files(self, query: str) -> ToolSonucu:
        if not query or not query.strip():
            return ToolSonucu(False, "HATA: query boş olamaz")
        # İçe aktarma burada: indeks modülü bu modülü kullandığı için döngüsel
        # import'u kırmak gerekiyor
        from orchestrator.indeks import RepoIndeksi

        try:
            return ToolSonucu(True, RepoIndeksi(self.workspace).sorgula_metin(query))
        except Exception as e:  # örn. embedding arka ucu yapılandırma/ağ hatası
            return ToolSonucu(False, f"HATA: arama başarısız: {e}")

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

    def start_server(self, command: str, port: int) -> ToolSonucu:
        if not command or not command.strip():
            return ToolSonucu(False, "HATA: command boş olamaz")
        try:
            port = int(port)
        except (TypeError, ValueError):
            return ToolSonucu(False, "HATA: port bir sayı olmalı")
        mesaj = self.sunucu_yoneticisi.baslat(command, port)
        return ToolSonucu(not mesaj.startswith("HATA"), mesaj)

    def stop_server(self, port: int) -> ToolSonucu:
        try:
            port = int(port)
        except (TypeError, ValueError):
            return ToolSonucu(False, "HATA: port bir sayı olmalı")
        mesaj = self.sunucu_yoneticisi.durdur(port)
        return ToolSonucu(not mesaj.startswith("HATA"), mesaj)

    def server_log(self, port: int) -> ToolSonucu:
        try:
            port = int(port)
        except (TypeError, ValueError):
            return ToolSonucu(False, "HATA: port bir sayı olmalı")
        mesaj = self.sunucu_yoneticisi.log(port)
        return ToolSonucu(not mesaj.startswith("HATA"), _kes(mesaj))

    def _dev_server_gerekli(self, dosya: Path, path: str) -> str | None:
        """file:// ile açılması anlamsız sayfaları yakalar (Vite/Next vb.).

        Dev-server projelerinde modüller file:// altında YÜKLENMEZ; konsol temiz
        görünür, "React is not defined" gibi hatalar hiç oluşmaz ve Validator
        yanlış "geçti" der (canlıda görüldü). Bu yüzden iki işaretten biri varsa
        dosya yoluyla açma mekanik olarak reddedilir ve modele doğru akış söylenir:

        1. Dosyanın dizininden workspace köküne dek en yakın package.json bir
           dev-server'a işaret ediyorsa (``"dev"`` scripti veya vite/next/react-scripts)
        2. HTML, kökten mutlak (``src="/..."``) bir ES modülü yüklüyorsa
           (file:// altında bu yol dosya sistemi köküne çözülür ve kırılır)
        """
        if dosya.suffix.lower() not in (".html", ".htm"):
            return None

        # 1) Yakın package.json dev-server'a mı işaret ediyor?
        dizin = dosya.parent
        while True:
            paket = dizin / "package.json"
            if paket.is_file():
                icerik = paket.read_text(encoding="utf-8", errors="replace").lower()
                if '"dev"' in icerik or any(
                    im in icerik for im in ("vite", "next", "react-scripts")
                ):
                    return (
                        f"HATA: {path} bir dev-server projesine ait görünüyor "
                        f"({paket.relative_to(self.workspace).as_posix()} bulundu). "
                        "Dosyayı file:// ile açmak modülleri YÜKLEMEZ — konsol temiz "
                        "görünse de sayfa gerçekte çalışmıyor olabilir. Doğru akış: "
                        "1) bağımlılık kurulmadıysa run_shell ile kur "
                        "('npm install', timeout=600), 2) start_server ile dev "
                        "sunucusunu başlat (örn. 'npm run dev', Vite portu 5173), "
                        "3) check_page http://localhost:<port> ile doğrula, "
                        "4) bitince stop_server."
                    )
                break  # en yakın package.json karar verdi; yukarı bakma
            if dizin == self.workspace:
                break
            dizin = dizin.parent

        # 2) Kökten mutlak modül scripti file:// altında çözülmez
        html = dosya.read_text(encoding="utf-8", errors="replace")[:64_000]
        for etiket in re.findall(r"<script\b[^>]*>", html, re.IGNORECASE):
            if "module" in etiket and re.search(r"""src=["']/(?!/)""", etiket):
                return (
                    f"HATA: {path} kökten mutlak yollu bir ES modülü yüklüyor "
                    f"(örn. {etiket[:120]}). file:// altında '/...' yolu çözülmez; "
                    "sayfa bir sunucu üzerinden doğrulanmalı. Akış: start_server ile "
                    "sunucu başlat (dev-server projesiyse 'npm run dev', düz statik "
                    "siteyse 'python -m http.server 8000'), sonra "
                    "check_page http://localhost:<port> kullan."
                )
        return None

    def check_page(self, path: str) -> ToolSonucu:
        """Sayfayı headless tarayıcıda açar: hatalar + screenshot + görsel analiz.

        path bir dosya yolu (file://) veya canlı sunucu URL'si
        (http://localhost:PORT) olabilir — ikincisi start_server ile birlikte
        çalışan React/backend'i görsel doğrulamak için.
        """
        canli = path.startswith(("http://", "https://"))
        if canli:
            hedef_url = path
            ekran_adi = "canli"
        else:
            try:
                tam = self._coz(path)
            except ValueError as e:
                return ToolSonucu(False, f"HATA: {e}")
            if not tam.is_file():
                return ToolSonucu(False, f"HATA: dosya bulunamadı: {path!r}")
            engel = self._dev_server_gerekli(tam, path)
            if engel:
                return ToolSonucu(False, engel)
            hedef_url = tam.as_uri()
            ekran_adi = tam.stem

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ToolSonucu(
                False,
                "HATA: playwright kurulu değil. Kurulum: uv sync && "
                "uv run playwright install chromium",
            )

        konsol_hatalari: list[str] = []
        try:
            with sync_playwright() as p:
                tarayici = p.chromium.launch(headless=True)
                sayfa = tarayici.new_page()
                sayfa.on(
                    "console",
                    lambda m: konsol_hatalari.append(f"[{m.type}] {m.text}")
                    if m.type in ("error", "warning")
                    else None,
                )
                sayfa.on("pageerror", lambda e: konsol_hatalari.append(f"[pageerror] {e}"))
                sayfa.goto(hedef_url, wait_until="load", timeout=30_000)
                sayfa.wait_for_timeout(400)  # geç çalışan scriptlere pay
                baslik = sayfa.title()

                kontrol = self.workspace / ".kontrol"
                kontrol.mkdir(exist_ok=True)
                ekran = kontrol / (ekran_adi + ".png")
                sayfa.screenshot(path=str(ekran), full_page=True)
                tarayici.close()
        except Exception as e:  # tarayıcı açılamadı / sayfa yüklenemedi
            return ToolSonucu(False, f"HATA: sayfa açılamadı: {e}")

        parcalar = [f"Sayfa açıldı: {path} (başlık: {baslik or '(boş)'})"]
        if konsol_hatalari:
            parcalar.append("Konsol hataları:\n" + "\n".join(konsol_hatalari[:20]))
        else:
            parcalar.append("Konsol: temiz (hata/uyarı yok)")
        parcalar.append(f"Ekran görüntüsü: {ekran.relative_to(self.workspace).as_posix()}")

        # Görsel analiz (opsiyonel; anahtar yoksa sessizce atlanır) — içe aktarma
        # burada: gorsel modülü httpx kullanır, döngüsel bağımlılık yok ama tembel
        # tutmak testlerde sahtelemeyi kolaylaştırır
        from orchestrator.gorsel import gorsel_acik, gorsel_analiz

        if gorsel_acik():
            analiz = gorsel_analiz(ekran)
            if analiz:
                parcalar.append(f"Görsel analiz (Gemini):\n{analiz}")
        return ToolSonucu(True, _kes("\n\n".join(parcalar)))

    def edit_file(self, path: str, eski_metin: str, yeni_metin: str) -> ToolSonucu:
        """Dosyada eski_metni yeni_metinle değiştirir (birebir, benzersiz eşleşme)."""
        try:
            tam = self._coz(path)
        except ValueError as e:
            return ToolSonucu(False, f"HATA: {e}")
        if not tam.is_file():
            return ToolSonucu(False, f"HATA: dosya bulunamadı: {path!r}")
        if not eski_metin:
            return ToolSonucu(False, "HATA: eski_metin boş olamaz")

        icerik = tam.read_text(encoding="utf-8", errors="replace")
        adet = icerik.count(eski_metin)
        if adet == 0:
            return ToolSonucu(
                False,
                "HATA: eski_metin dosyada bulunamadı (birebir eşleşmeli — boşluk/girinti "
                "dahil). read_file ile güncel içeriği kontrol et.",
            )
        if adet > 1:
            return ToolSonucu(
                False,
                f"HATA: eski_metin dosyada {adet} kez geçiyor; benzersiz olmalı. "
                "Çevresine bağlam ekleyerek tek eşleşme sağla.",
            )

        yeni_icerik = icerik.replace(eski_metin, yeni_metin)
        tam.write_text(yeni_icerik, encoding="utf-8", newline="\n")
        diff = "".join(
            difflib.unified_diff(
                icerik.splitlines(keepends=True),
                yeni_icerik.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        return ToolSonucu(True, f"{path} düzenlendi.\n\n{_kes(diff)}")

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
        if ad == "search_files":
            return self.search_files(girdi.get("query", ""))
        if ad == "check_page":
            return self.check_page(girdi.get("path", ""))
        if ad == "start_server":
            return self.start_server(girdi.get("command", ""), girdi.get("port"))
        if ad == "stop_server":
            return self.stop_server(girdi.get("port"))
        if ad == "server_log":
            return self.server_log(girdi.get("port"))
        if ad == "read_file":
            return self.read_file(girdi.get("path", ""))
        if ad == "write_file":
            return self.write_file(girdi.get("path", ""), girdi.get("content", ""))
        if ad == "edit_file":
            return self.edit_file(
                girdi.get("path", ""),
                girdi.get("eski_metin", ""),
                girdi.get("yeni_metin", ""),
            )
        if ad == "run_shell":
            return self.run_shell(girdi.get("command", ""), girdi.get("timeout"))
        return ToolSonucu(False, f"HATA: bilinmeyen araç: {ad!r}")
