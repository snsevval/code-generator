"""Faz 8 — Arka plan süreç yönetimi (full-stack yeteneği).

Ajanların bitmeyen süreçleri (dev sunucu, API sunucusu) başlatıp
canlıyken doğrulayıp durdurabilmesi için. `run_shell` yalnızca biten
komutları koşabiliyor; `npm run dev` / `uvicorn` gibi sonsuz süreçler
onu asardı.

Kritik güvence: sızıntı önleme. Her sunucu bir port'a bağlanır; görev
bitince SunucuYoneticisi.hepsini_durdur() tüm süreç AĞACINI öldürür
(Windows'ta npm/node alt süreçler açar → taskkill /T; POSIX'te process
group → killpg).
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PORT_BEKLEME_SN = 60.0  # sunucunun port'u dinlemeye başlaması için azami süre
LOG_KUYRUK_KARAKTER = 4000  # server_log'un döndürdüğü son log uzunluğu


def port_dinliyor_mu(port: int, host: str | None = None) -> bool:
    """Port'a TCP bağlantısı kurulabiliyor mu (sunucu ayakta mı)?

    Hem IPv4 (127.0.0.1) hem IPv6 (::1) denenir: Vite/Node gibi araçlar
    ``localhost``'u varsayılan olarak IPv6 ``::1``'e bağlar, yalnızca IPv4'e
    bakmak sunucuyu "kapalı" sanmaya yol açar (canlıda Vite bu yüzden
    algılanamadı).
    """
    hedefler = [host] if host else ["127.0.0.1", "::1"]
    for h in hedefler:
        aile = socket.AF_INET6 if ":" in h else socket.AF_INET
        try:
            with contextlib.closing(socket.socket(aile, socket.SOCK_STREAM)) as s:
                s.settimeout(1.0)
                if s.connect_ex((h, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def bos_port_bul() -> int:
    """OS'tan boş bir TCP portu ister (127.0.0.1'e 0 portuyla bağlanıp okur).

    Deterministik Runner'ın sunucuları için: portu MODEL değil orkestratör seçer,
    böylece port çakışması/dansı olmaz. Bağlama ile gerçek kullanım arasında küçük
    bir TOCTOU penceresi var ama yerel tek-görev akışında ihmal edilebilir.
    """
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class Sunucu:
    port: int
    komut: str
    surec: subprocess.Popen
    log_yolu: Path


@dataclass
class SunucuYoneticisi:
    """Bir görev boyunca açılan arka plan sunucularını yönetir ve temizler."""

    workspace: Path
    sunucular: dict[int, Sunucu] = field(default_factory=dict)

    def _log_dizini(self) -> Path:
        d = self.workspace / ".sunucu"
        d.mkdir(exist_ok=True)
        return d

    def baslat(self, komut: str, port: int, hazir_metni: str | None = None) -> str:
        """Sunucuyu arka planda başlatır; port dinlemeye başlayınca döner.

        hazir_metni verilirse, port kontrolüne ek olarak logda o metnin
        görünmesi de beklenir (bazı sunucular portu erken açar).
        """
        if port in self.sunucular:
            return f"HATA: {port} portunda zaten bir sunucu var; önce durdur."
        if port_dinliyor_mu(port):
            return f"HATA: {port} portu başka bir süreç tarafından kullanılıyor."

        log_yolu = self._log_dizini() / f"{port}.log"
        log_dosyasi = open(log_yolu, "w", encoding="utf-8", errors="replace")
        # Süreç ağacını topluca öldürebilmek için: Windows'ta yeni süreç grubu,
        # POSIX'te yeni oturum (setsid)
        ekstra: dict = {}
        if sys.platform == "win32":
            ekstra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            ekstra["start_new_session"] = True

        surec = subprocess.Popen(
            komut,
            shell=True,
            cwd=self.workspace,
            stdout=log_dosyasi,
            stderr=subprocess.STDOUT,
            **ekstra,
        )

        son = time.monotonic() + PORT_BEKLEME_SN
        while time.monotonic() < son:
            if surec.poll() is not None:
                log_dosyasi.close()
                kuyruk = self._log_oku(log_yolu)
                return (
                    f"HATA: sunucu başlamadan çıktı (kod {surec.returncode}).\n"
                    f"Son log:\n{kuyruk}"
                )
            hazir = port_dinliyor_mu(port)
            if hazir and hazir_metni:
                hazir = hazir_metni in self._log_oku(log_yolu)
            if hazir:
                self.sunucular[port] = Sunucu(port, komut, surec, log_yolu)
                return (
                    f"Sunucu {port} portunda çalışıyor (PID {surec.pid}). "
                    f"check_page ile http://localhost:{port} açılabilir; "
                    "iş bitince stop_server ile durdur."
                )
            time.sleep(0.5)

        # Zaman aşımı: süreci temizle
        self._oldur(surec)
        log_dosyasi.close()
        return (
            f"HATA: sunucu {PORT_BEKLEME_SN:.0f} saniyede {port} portunu açmadı.\n"
            f"Son log:\n{self._log_oku(log_yolu)}"
        )

    def durdur(self, port: int) -> str:
        sunucu = self.sunucular.pop(port, None)
        if sunucu is None:
            return f"HATA: {port} portunda yönetilen bir sunucu yok."
        self._oldur(sunucu.surec)
        return f"Sunucu {port} durduruldu."

    def log(self, port: int) -> str:
        sunucu = self.sunucular.get(port)
        if sunucu is None:
            return f"HATA: {port} portunda yönetilen bir sunucu yok."
        return self._log_oku(sunucu.log_yolu)

    def hepsini_durdur(self) -> None:
        """Görev sonu temizliği: tüm sunucuları durdurur (sızıntı önleme)."""
        for port in list(self.sunucular):
            with contextlib.suppress(Exception):
                self.durdur(port)

    # --- iç yardımcılar ---

    @staticmethod
    def _log_oku(yol: Path) -> str:
        try:
            metin = yol.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(log okunamadı)"
        return metin[-LOG_KUYRUK_KARAKTER:]

    @staticmethod
    def _oldur(surec: subprocess.Popen) -> None:
        """Süreç ağacını topluca öldürür (alt süreçler dahil)."""
        if surec.poll() is not None:
            return
        try:
            if sys.platform == "win32":
                # npm/node ağacını komple öldür
                subprocess.run(
                    ["taskkill", "/PID", str(surec.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                )
            else:
                os.killpg(os.getpgid(surec.pid), signal.SIGTERM)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    surec.wait(timeout=5)
                if surec.poll() is None:
                    os.killpg(os.getpgid(surec.pid), signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            with contextlib.suppress(Exception):
                surec.kill()
