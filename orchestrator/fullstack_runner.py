"""Aşama 1 — Deterministik Full-stack Runner.

Koreografiyi (pytest çalıştırma, port seçimi, sunucu başlat/bekle, uç deneme)
MODELDEN alıp orkestratöre verir. Model yalnızca dosyaları (ve varsa küçük bir
`calisma.json` manifestini) üretir; doğrulama tamamen deterministik ve
tekrarlanabilir olur.

Neden (canlı gözlem, 2026-07-17, aynı backend görevi 3 koşu):
- Koşu 1: Codegen hiç dosya yazmadı, model validator hiç kod yokken 'BASARILI'
  halüsinasyonu yaptı → SAHTE geçiş.
- Koşu 2: kod doğruydu ama validator 175k token debelendi (olmayan dosyalar,
  olmayan uçlar).
- Koşu 3: temiz — ama şans eseri.
Deterministik koşu bu yazı-turayı ortadan kaldırır: kod yoksa/pytest patlarsa
BAŞARISIZ; sunucu ayağa kalkıp serve ediyorsa BAŞARILI — halüsinasyon imkânsız.

Aşama 1 kapsamı: BACKEND (pytest + uvicorn + /openapi.json serve kontrolü).
Frontend/check_page ile full-stack sonraki dalga.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

from orchestrator.sunucu import SunucuYoneticisi, bos_port_bul

PYTEST_ZAMAN_ASIMI_SN = 120.0
HTTP_ZAMAN_ASIMI_SN = 10.0
SAYFA_ZAMAN_ASIMI_MS = 30_000
FETCH_BEKLEME_MS = 1000  # networkidle sonrası geç fetch'lere pay

# Görev klasörüne konan sistem dosyaları — "kod üretilmedi" kontrolünde sayılmaz
_SISTEM_DOSYALARI = {"pytest.ini", "conftest.py", "calisma.json"}
_FASTAPI_DESENI = re.compile(r"(\w+)\s*=\s*FastAPI\s*\(")
# Modül adayı tercih sırası (çok FastAPI dosyası varsa)
_MODUL_TERCIHI = ("backend", "main", "app", "api")


def _izole_pytest_env() -> dict:
    """pytest'i host eklentilerinden yalıtan temiz subprocess ortamı.

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1: pytest-docker gibi alakasız eklentiler
    yüklenmez (canlıda model bunu 'sorun' sanıp `pip uninstall`a kalkışmıştı).
    PYTEST_ADDOPTS temizlenir: host'tan sızan ekstra bayraklar koşuyu etkilemesin.
    rootdir zaten görev klasöründeki pytest.ini/conftest ile kilitli.
    """
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return env


@dataclass
class DogrulamaRaporu:
    """Deterministik doğrulamanın sonucu (orkestratöre döner)."""

    gecti: bool
    detay: str


def fastapi_uygulamasi_bul(workspace: Path) -> tuple[str, str] | None:
    """Workspace'te FastAPI uygulaması içeren modülü bulur → (modül_adı, değişken).

    Test/konfig dosyaları atlanır. Birden çok aday varsa tercih sırası uygulanır
    (backend > main > app > api > alfabetik). Bulamazsa None.
    """
    adaylar: dict[str, str] = {}  # modül_adı -> app değişkeni
    for py in sorted(workspace.glob("*.py")):
        if py.name in _SISTEM_DOSYALARI or py.name.startswith("test_"):
            continue
        try:
            icerik = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        eslesme = _FASTAPI_DESENI.search(icerik)
        if eslesme:
            adaylar[py.stem] = eslesme.group(1)
    if not adaylar:
        return None
    for tercih in _MODUL_TERCIHI:
        if tercih in adaylar:
            return tercih, adaylar[tercih]
    ad = sorted(adaylar)[0]
    return ad, adaylar[ad]


def manifest_oku(workspace: Path) -> dict:
    """Varsa calisma.json manifestini okur (yoksa boş sözlük). Bozuksa yok sayar."""
    yol = workspace / "calisma.json"
    if not yol.is_file():
        return {}
    try:
        veri = json.loads(yol.read_text(encoding="utf-8", errors="replace"))
        return veri if isinstance(veri, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


class FullstackRunner:
    """Backend/full-stack görevlerini deterministik doğrular (model karışmadan)."""

    def __init__(self, workspace: Path | str, log=None):
        self.workspace = Path(workspace).resolve()
        self._log = log

    def _yaz(self, mesaj: str) -> None:
        if callable(self._log):
            self._log(mesaj)

    # --- Backend doğrulama ---

    def backend_dogrula(self) -> DogrulamaRaporu:
        """Backend'i uçtan uca deterministik doğrular; DogrulamaRaporu döndürür.

        Sıra: (1) kod var mı, (2) pytest izole geçiyor mu, (3) uvicorn ayağa
        kalkıp /openapi.json serve ediyor mu. Herhangi biri düşerse net gerekçeyle
        BAŞARISIZ — model validator'ın 'BASARILI' halüsinasyonu buraya giremez.
        """
        # 1) Kod üretilmiş mi? (sistem dosyaları sayılmaz)
        uygulama = fastapi_uygulamasi_bul(self.workspace)
        if uygulama is None:
            uretilenler = [
                p.name for p in self.workspace.glob("*.py") if p.name not in _SISTEM_DOSYALARI
            ]
            return DogrulamaRaporu(
                False,
                "BAŞARISIZ: FastAPI uygulaması (app = FastAPI()) içeren bir modül "
                f"bulunamadı. Üretilen .py dosyaları: {uretilenler or '(yok)'}. "
                "Codegen backend kodunu yazmamış olabilir.",
            )
        modul, app_degiskeni = uygulama

        # 2) Test var mı ve izole pytest geçiyor mu?
        test_dosyalari = [p.name for p in self.workspace.glob("test_*.py")]
        if not test_dosyalari:
            return DogrulamaRaporu(
                False,
                f"BAŞARISIZ: hiç test dosyası (test_*.py) yok. {modul}.py yazılmış ama "
                "pytest ile test edilmemiş; görev testleri de gerektiriyor.",
            )
        self._yaz(f"[runner] pytest (izole) çalışıyor: {', '.join(test_dosyalari)}")
        pytest_sonuc = self._pytest_kos()
        if not pytest_sonuc.gecti:
            return pytest_sonuc  # detay: pytest çıktısı

        # 3) Sunucu ayağa kalkıp serve ediyor mu?
        return self._sunucu_dogrula(modul, app_degiskeni)

    def _pytest_kos(self) -> DogrulamaRaporu:
        try:
            sonuc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"],
                cwd=self.workspace,
                env=_izole_pytest_env(),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=PYTEST_ZAMAN_ASIMI_SN,
            )
        except subprocess.TimeoutExpired:
            return DogrulamaRaporu(
                False, f"BAŞARISIZ: pytest {PYTEST_ZAMAN_ASIMI_SN:.0f} sn'de bitmedi (zaman aşımı)."
            )
        cikti = (sonuc.stdout + "\n" + sonuc.stderr).strip()
        if sonuc.returncode == 0:
            return DogrulamaRaporu(True, "pytest geçti.\n" + cikti[-1500:])
        return DogrulamaRaporu(
            False,
            "BAŞARISIZ: pytest başarısız (çıkış kodu "
            f"{sonuc.returncode}). Çıktı:\n{cikti[-2500:]}",
        )

    def _sunucu_dogrula(self, modul: str, app_degiskeni: str) -> DogrulamaRaporu:
        port = bos_port_bul()
        komut = (
            f'"{sys.executable}" -m uvicorn {modul}:{app_degiskeni} '
            f"--port {port} --host 127.0.0.1"
        )
        yonetici = SunucuYoneticisi(self.workspace)
        self._yaz(f"[runner] uvicorn başlatılıyor (port {port})")
        mesaj = yonetici.baslat(komut, port)
        try:
            if mesaj.startswith("HATA"):
                return DogrulamaRaporu(
                    False, f"BAŞARISIZ: backend sunucusu ayağa kalkmadı.\n{mesaj}"
                )
            # /openapi.json her FastAPI uygulamasında vardır → import + serve kanıtı
            try:
                yanit = httpx.get(
                    f"http://127.0.0.1:{port}/openapi.json", timeout=HTTP_ZAMAN_ASIMI_SN
                )
            except httpx.HTTPError as e:
                return DogrulamaRaporu(
                    False, f"BAŞARISIZ: sunucu ayakta ama yanıt vermedi: {e}"
                )
            if yanit.status_code != 200:
                return DogrulamaRaporu(
                    False,
                    f"BAŞARISIZ: /openapi.json HTTP {yanit.status_code} döndü "
                    "(uygulama düzgün yüklenmemiş olabilir).",
                )
            uc_sayisi = len(yanit.json().get("paths", {}))
            return DogrulamaRaporu(
                True,
                f"BAŞARILI: pytest geçti; {modul}:{app_degiskeni} uvicorn'da ayağa "
                f"kalktı ve {uc_sayisi} uç serve ediyor (/openapi.json 200).",
            )
        finally:
            yonetici.hepsini_durdur()

    # --- Full-stack doğrulama (backend + frontend + entegrasyon kanıtı) ---

    def _frontend_dosyasi_bul(self) -> Path | None:
        """Arayüz giriş dosyasını bulur (önce index.html, sonra herhangi bir .html)."""
        tercih = self.workspace / "index.html"
        if tercih.is_file():
            return tercih
        for html in sorted(self.workspace.rglob("*.html")):
            return html
        return None

    def fullstack_dogrula(self) -> DogrulamaRaporu:
        """Full-stack'i deterministik doğrular: pytest + backend + frontend + ENTEGRASYON.

        Kritik adım entegrasyon kanıtıdır: frontend gerçekten backend'e fetch atıp
        veri çekiyor mu? Çekmiyorsa (bağımsız sayfa) BAŞARISIZ — 'iki ayrı uygulama'
        sorunu buraya giremez.
        """
        uygulama = fastapi_uygulamasi_bul(self.workspace)
        if uygulama is None:
            return DogrulamaRaporu(
                False, "BAŞARISIZ: FastAPI backend'i (app = FastAPI()) bulunamadı."
            )
        modul, app_degiskeni = uygulama
        index = self._frontend_dosyasi_bul()
        if index is None:
            return DogrulamaRaporu(
                False, "BAŞARISIZ: frontend dosyası (index.html) bulunamadı."
            )
        # Backend testleri varsa geçmeli (mantık doğruluğu)
        if list(self.workspace.glob("test_*.py")):
            self._yaz("[runner] pytest (izole) çalışıyor")
            pytest_sonuc = self._pytest_kos()
            if not pytest_sonuc.gecti:
                return pytest_sonuc
        return self._entegrasyon_dogrula(modul, app_degiskeni, index)

    def _entegrasyon_dogrula(self, modul: str, app_degiskeni: str, index: Path) -> DogrulamaRaporu:
        """TEK-ORIGIN: backend'i boş bir portta başlatır (index.html'i de o servis eder),
        sayfayı açıp frontend'in backend'e fetch attığını AĞ düzeyinde kanıtlar."""
        port = bos_port_bul()
        yonetici = SunucuYoneticisi(self.workspace)
        try:
            komut = (
                f'"{sys.executable}" -m uvicorn {modul}:{app_degiskeni} '
                f"--port {port} --host 127.0.0.1"
            )
            self._yaz(f"[runner] backend (index.html'i de servis eder) başlatılıyor (port {port})")
            mesaj = yonetici.baslat(komut, port)
            if mesaj.startswith("HATA"):
                return DogrulamaRaporu(False, f"BAŞARISIZ: backend başlamadı.\n{mesaj}")

            url = f"http://127.0.0.1:{port}/"
            self._yaz(f"[runner] entegrasyon kontrolü (tek-origin): {url}")
            return self._baglanti_kontrol(url, port)
        finally:
            yonetici.hepsini_durdur()

    def _baglanti_kontrol(self, url: str, port: int) -> DogrulamaRaporu:
        """Sayfayı tarayıcıda açıp aynı origin'e fetch/XHR atıp attığını AĞ düzeyinde kanıtlar.

        Kanıt = sayfa yüklenirken aynı origin'e (backend port) en az bir BAŞARILI (2xx/3xx)
        fetch/XHR isteği gitmesi + konsolun temiz olması. Hiç API isteği yoksa frontend
        bağımsızdır (örn. sadece yerel sayaç) → BAŞARISIZ. İstek gidip başarısızsa → BAŞARISIZ.
        (Statik varlıklar — HTML/CSS/font — sayılmaz; yalnız fetch/xhr kaynak tipi sayılır.)
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return DogrulamaRaporu(
                False,
                "BAŞARISIZ: playwright kurulu değil, entegrasyon doğrulanamadı "
                "(uv run playwright install chromium).",
            )
        konsol_hatalari: list[str] = []
        api_yanitlari: list[tuple[str, int]] = []  # yalnız fetch/xhr istekleri
        isaret = f":{port}"

        def _yanit(r) -> None:
            try:
                if r.request.resource_type in ("fetch", "xhr") and isaret in r.url:
                    api_yanitlari.append((r.url, r.status))
            except Exception:
                pass

        try:
            with sync_playwright() as p:
                tarayici = p.chromium.launch(headless=True)
                sayfa = tarayici.new_page()
                sayfa.on(
                    "console",
                    lambda m: konsol_hatalari.append(m.text) if m.type == "error" else None,
                )
                sayfa.on("pageerror", lambda e: konsol_hatalari.append(str(e)))
                sayfa.on("response", _yanit)
                sayfa.goto(url, wait_until="networkidle", timeout=SAYFA_ZAMAN_ASIMI_MS)
                sayfa.wait_for_timeout(FETCH_BEKLEME_MS)
                tarayici.close()
        except Exception as e:  # tarayıcı/sayfa hatası
            return DogrulamaRaporu(False, f"BAŞARISIZ: sayfa açılamadı/doğrulanamadı: {e}")

        basarili = [(u, s) for (u, s) in api_yanitlari if 200 <= s < 400]
        if not api_yanitlari:
            return DogrulamaRaporu(
                False,
                "BAŞARISIZ: frontend backend'e (aynı origin) HİÇ fetch/XHR isteği atmadı — "
                "arayüz backend'e bağlı değil (bağımsız sayfa). index.html sayfa yüklenince "
                "GÖRELİ yolla (fetch('/todos')) backend'den veri çekip DOM'a basmalı.",
            )
        if not basarili:
            durumlar = ", ".join(f"{s}" for _, s in api_yanitlari[:5])
            return DogrulamaRaporu(
                False,
                f"BAŞARISIZ: frontend backend'e istek attı ama başarısız (durum kodları: "
                f"{durumlar}). Yanlış uç/yol olabilir.",
            )
        if konsol_hatalari:
            return DogrulamaRaporu(
                False,
                "BAŞARISIZ: veri isteği gitti ama sayfada konsol hatası var:\n"
                + "\n".join(konsol_hatalari[:5]),
            )
        return DogrulamaRaporu(
            True,
            f"BAŞARILI: tek-origin — frontend backend'den veri çekti "
            f"({len(basarili)} başarılı fetch, konsol temiz).",
        )
