"""Faz 3 — UI backend API testleri (sahte orkestratörle, ağsız).

Çalıştırma:
    uv run pytest tests/test_api.py -v
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from orchestrator import api
from orchestrator.state import OturumState


class SahteOrkestrator:
    """Gerçek LLM'e gitmeden log üretip sonuç döndüren sahte orkestratör."""

    def __init__(self, log, beklet: float = 0.0, patla: bool = False):
        self._log = log
        self._beklet = beklet
        self._patla = patla

    def gorev_calistir(self, gorev: str, devam: bool = False) -> OturumState:
        self._log("[planner] başlıyor...")
        if self._beklet:
            time.sleep(self._beklet)
        if self._patla:
            raise RuntimeError("sahte çökme")
        self._log("[reviewer] bitti.")
        state = OturumState(gorev=gorev)
        state.ciktilar = {"dogrulama_gecti": "True", "reviewer": "rapor", "planner": "plan"}
        return state


@pytest.fixture
def istemci(monkeypatch, tmp_path):
    monkeypatch.setenv("FCC_WORKSPACE", str(tmp_path / "ws"))
    # Her test temiz durumla başlasın
    api.DURUM.__init__()
    return TestClient(api.app)


def _bekle_bitsin(istemci, sn: float = 5.0) -> dict:
    """Arka plan görevi bitene dek durumu yoklar."""
    son = time.monotonic() + sn
    while time.monotonic() < son:
        veri = istemci.get("/api/durum").json()
        if not veri["calisiyor"]:
            return veri
        time.sleep(0.05)
    raise AssertionError("görev zamanında bitmedi")


def test_gorev_baslat_ve_sonuc(istemci, monkeypatch):
    monkeypatch.setattr(
        api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: SahteOrkestrator(log)
    )
    yanit = istemci.post("/api/gorev", json={"gorev": "bir şey yap"})
    assert yanit.status_code == 200

    veri = _bekle_bitsin(istemci)
    assert veri["hata"] is None
    assert veri["sonuc"]["dogrulama_gecti"] is True
    assert veri["sonuc"]["reviewer"] == "rapor"
    assert "[planner] başlıyor..." in veri["log"]


def test_ayni_anda_tek_gorev(istemci, monkeypatch):
    monkeypatch.setattr(
        api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: SahteOrkestrator(log, beklet=0.5)
    )
    assert istemci.post("/api/gorev", json={"gorev": "birinci"}).status_code == 200
    ikinci = istemci.post("/api/gorev", json={"gorev": "ikinci"})
    assert ikinci.status_code == 409
    _bekle_bitsin(istemci)


def test_bos_gorev_reddedilir(istemci):
    assert istemci.post("/api/gorev", json={"gorev": "   "}).status_code == 422


def test_cokme_hata_olarak_doner(istemci, monkeypatch):
    monkeypatch.setattr(
        api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: SahteOrkestrator(log, patla=True)
    )
    istemci.post("/api/gorev", json={"gorev": "patla"})
    veri = _bekle_bitsin(istemci)
    assert veri["hata"] is not None
    assert "sahte çökme" in veri["hata"]
    assert veri["sonuc"] is None
    # Çökme sonrası yeni görev başlatılabilmeli
    monkeypatch.setattr(
        api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: SahteOrkestrator(log)
    )
    assert istemci.post("/api/gorev", json={"gorev": "tekrar"}).status_code == 200
    _bekle_bitsin(istemci)


def test_durum_kullanim_alani_icerir(istemci):
    veri = istemci.get("/api/durum").json()
    assert "kullanim" in veri  # koşu yokken None olabilir


def test_iptal_calisan_gorev_yokken(istemci):
    # Çalışan görev yokken iptal no-op döner (hata değil)
    veri = istemci.post("/api/iptal").json()
    assert veri["iptal"] is False


def test_iptal_calisan_gorevi_durdurur(istemci, monkeypatch):
    # Uzun süren görev + iptal: orkestratör iptal_kontrol'ü görüp durur, calisiyor False olur
    import threading

    baslasin = threading.Event()

    class YavasOrk(SahteOrkestrator):
        def __init__(self, log):
            super().__init__(log)
            self.iptal_kontrol = None

        def gorev_calistir(self, gorev, devam=False):
            baslasin.set()
            # iptal gelene kadar bekle, sonra IptalEdildi fırlat (orkestratör davranışı)
            for _ in range(200):
                if callable(self.iptal_kontrol) and self.iptal_kontrol():
                    from orchestrator.loop import IptalEdildi

                    raise IptalEdildi("iptal")
                time.sleep(0.02)
            return super().gorev_calistir(gorev, devam)

    monkeypatch.setattr(api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: YavasOrk(log))
    istemci.post("/api/gorev", json={"gorev": "uzun görev"})
    assert baslasin.wait(timeout=5)
    assert istemci.post("/api/iptal").json()["iptal"] is True
    veri = _bekle_bitsin(istemci)
    assert veri["calisiyor"] is False
    assert veri["hata"] == "Görev iptal edildi."


def test_tasarim_bayragi_gorevi_zenginlestirir(istemci, monkeypatch):
    alinan = {}

    class KaydediciOrk(SahteOrkestrator):
        def gorev_calistir(self, gorev, devam=False):
            alinan["gorev"] = gorev
            return super().gorev_calistir(gorev, devam)

    monkeypatch.setattr(
        api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: KaydediciOrk(log)
    )
    monkeypatch.setattr(api, "TASARIM_ZENGINLESTIRICI", lambda g: g + "\n\nUyulacak tasarım sistemi:\n- mor")

    istemci.post("/api/gorev", json={"gorev": "sayfa yap", "tasarim": True})
    veri = _bekle_bitsin(istemci)

    assert veri["hata"] is None
    assert "Uyulacak tasarım sistemi" in alinan["gorev"]
    assert any("[tasarım]" in s for s in veri["log"])


def test_dosyalar_listeler_ve_indirir(istemci, tmp_path):
    (tmp_path / "arac.py").write_text("print('selam')", encoding="utf-8")
    (tmp_path / "alt").mkdir()
    (tmp_path / "alt" / "veri.json").write_text("{}", encoding="utf-8")
    api.DURUM.klasor_yolu = tmp_path

    liste = istemci.get("/api/dosyalar").json()["dosyalar"]
    assert [d["ad"] for d in liste] == ["alt/veri.json", "arac.py"]
    assert liste[1]["boyut"] > 0

    # Görüntüleme: düz metin döner
    goruntu = istemci.get("/api/dosya", params={"ad": "arac.py"})
    assert goruntu.status_code == 200
    assert "print('selam')" in goruntu.text

    # İndirme: ek dosya başlığıyla döner
    indirme = istemci.get("/api/dosya", params={"ad": "arac.py", "indir": "1"})
    assert indirme.status_code == 200
    assert "attachment" in indirme.headers.get("content-disposition", "")


def test_dosya_path_traversal_reddedilir(istemci, tmp_path):
    (tmp_path / "ic").mkdir()
    api.DURUM.klasor_yolu = tmp_path / "ic"
    (tmp_path / "gizli.txt").write_text("sır", encoding="utf-8")

    yanit = istemci.get("/api/dosya", params={"ad": "../gizli.txt"})
    assert yanit.status_code == 404


def test_dosya_klasor_yokken_404(istemci):
    assert istemci.get("/api/dosya", params={"ad": "x.py"}).status_code == 404
    assert istemci.get("/api/dosyalar").json() == {"dosyalar": []}


def test_onizle_baslat_package_json_yoksa_400(istemci, tmp_path):
    (tmp_path / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
    api.DURUM.klasor_yolu = tmp_path
    yanit = istemci.post("/api/onizle-baslat", json={"calisma_dizini": ""})
    assert yanit.status_code == 400
    assert "package.json" in yanit.json()["detail"]


def test_onizle_baslat_klasor_yokken_404(istemci):
    api.DURUM.klasor_yolu = None
    assert istemci.post("/api/onizle-baslat", json={}).status_code == 404


def test_onizle_baslat_traversal_reddedilir(istemci, tmp_path):
    ic = tmp_path / "ic"
    ic.mkdir()
    api.DURUM.klasor_yolu = ic
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")  # dışarıda
    yanit = istemci.post("/api/onizle-baslat", json={"calisma_dizini": ".."})
    assert yanit.status_code == 404


def test_onizle_durdur_hep_calisir(istemci):
    assert istemci.post("/api/onizle-durdur").json() == {"durduruldu": True}


def test_durum_onizleme_url_alani(istemci):
    assert "onizleme_url" in istemci.get("/api/durum").json()


def test_onizle_cok_dosyali_site_sunar(istemci, tmp_path):
    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="style.css"><h1>Merhaba</h1>'
        '<script src="script.js"></script>',
        encoding="utf-8",
    )
    (tmp_path / "style.css").write_text("body { background: #000; }", encoding="utf-8")
    (tmp_path / "script.js").write_text("console.log('ok')", encoding="utf-8")
    api.DURUM.klasor_yolu = tmp_path

    # HTML doğru content-type ile
    html = istemci.get("/onizle/index.html")
    assert html.status_code == 200
    assert "text/html" in html.headers["content-type"]
    assert "<h1>Merhaba</h1>" in html.text

    # Göreli varlıklar da aynı kökten sunulur (asıl düzeltme)
    css = istemci.get("/onizle/style.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    js = istemci.get("/onizle/script.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]

    # Path traversal
    (tmp_path.parent / "gizli.txt").write_text("sır", encoding="utf-8")
    assert istemci.get("/onizle/../gizli.txt").status_code in (403, 404)


def test_saglik_endpointi(istemci):
    veri = istemci.get("/api/saglik").json()
    assert veri["api"] is True
    assert isinstance(veri["proxy"], bool)


def test_onay_akisi(istemci, monkeypatch):
    """Onaylı proje modunda zincir kullanıcı kararını bekler; Durdur zinciri keser."""
    from orchestrator.state import ProjeState

    class OnayliSahteProje:
        def __init__(self, ws, orkestrator=None, log=None, onay_callback=None):
            self._onay = onay_callback

        def hedef_calistir(self, hedef, devam=False):
            alt1 = {"id": 1, "gorev": "ilk iş", "kabul": "", "durum": "basarili", "ozet": ""}
            alt2 = {"id": 2, "gorev": "ikinci iş", "kabul": "", "durum": "bekliyor", "ozet": ""}
            devam_mi = self._onay(alt1)  # gerçek akıştaki gibi bloklar
            if devam_mi:
                alt2["durum"] = "basarili"
            return ProjeState(hedef=hedef, alt_gorevler=[alt1, alt2])

    monkeypatch.setattr(api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: object())
    monkeypatch.setattr(api, "ProjeOrkestratoru", OnayliSahteProje)

    istemci.post("/api/gorev", json={"gorev": "hedef", "proje": True, "onayli": True})

    # Onay bekleyene dek yokla
    son = time.monotonic() + 5
    while time.monotonic() < son:
        veri = istemci.get("/api/durum").json()
        if veri["onay_bekleyen"]:
            break
        time.sleep(0.05)
    assert veri["onay_bekleyen"]["id"] == 1

    # Durdur kararı gönder → zincir ikinciyi koşmadan bitmeli
    yanit = istemci.post("/api/onay", json={"devam": False})
    assert yanit.status_code == 200

    veri = _bekle_bitsin(istemci)
    assert veri["onay_bekleyen"] is None
    durumlar = [a["durum"] for a in veri["sonuc"]["alt_gorevler"]]
    assert durumlar == ["basarili", "bekliyor"]


def test_onay_beklenmiyorken_karar_409(istemci):
    assert istemci.post("/api/onay", json={"devam": True}).status_code == 409


def test_proje_modu_alt_gorevleri_doner(istemci, monkeypatch):
    from orchestrator.state import ProjeState

    class SahteProje:
        def __init__(self, ws, orkestrator=None, log=None, onay_callback=None):
            self._log = log

        def hedef_calistir(self, hedef, devam=False):
            self._log("[decomposer] hedef alt görevlere bölünüyor...")
            return ProjeState(
                hedef=hedef,
                alt_gorevler=[
                    {"id": 1, "gorev": "a", "kabul": "", "durum": "basarili", "ozet": ""},
                    {"id": 2, "gorev": "b", "kabul": "", "durum": "basarisiz", "ozet": ""},
                ],
            )

    monkeypatch.setattr(api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: object())
    monkeypatch.setattr(api, "ProjeOrkestratoru", SahteProje)

    yanit = istemci.post("/api/gorev", json={"gorev": "büyük hedef", "proje": True})
    assert yanit.status_code == 200

    veri = _bekle_bitsin(istemci)
    assert veri["hata"] is None
    assert veri["sonuc"]["proje"] is True
    assert veri["sonuc"]["dogrulama_gecti"] is False  # biri başarısız
    assert [a["durum"] for a in veri["sonuc"]["alt_gorevler"]] == ["basarili", "basarisiz"]
    assert "[decomposer] hedef alt görevlere bölünüyor..." in veri["log"]


# --- Önizleme backend'i (başarılı fullstack/backend sonrası canlı kalır) ---


class _SahteSunucuYoneticisi:
    def __init__(self, ws):
        self.durduruldu = False

    def baslat(self, komut, port):
        return f"Sunucu {port} portunda çalışıyor (PID 1)."

    def hepsini_durdur(self):
        self.durduruldu = True


def test_onizleme_backendi_baslar_ve_durur(tmp_path, monkeypatch):
    from orchestrator import sunucu

    monkeypatch.setattr(sunucu, "SunucuYoneticisi", _SahteSunucuYoneticisi)
    (tmp_path / "backend.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )

    api._onizleme_backendini_baslat(tmp_path)
    # Dinamik port: URL http://localhost:<port> biçiminde olmalı (sabit port yok)
    assert api.DURUM.onizleme_backend_url is not None
    assert api.DURUM.onizleme_backend_url.startswith("http://localhost:")
    assert int(api.DURUM.onizleme_backend_url.rsplit(":", 1)[1]) > 0
    yonetici = api.DURUM.onizleme_backend_yoneticisi
    assert yonetici is not None

    api._onizleme_backendini_durdur()
    assert api.DURUM.onizleme_backend_url is None
    assert api.DURUM.onizleme_backend_yoneticisi is None
    assert yonetici.durduruldu is True


def test_basarisiz_ama_calisan_uygulama_onizleme_baslar(istemci, monkeypatch):
    # Test dosyası bozuk olsa da (dogrulama_gecti False) uygulama çalışıyorsa (backend
    # ayağa kalkıyorsa) önizleme AÇILMALI — çalışan uygulamayı görmek engellenmemeli
    from orchestrator import sunucu

    monkeypatch.setattr(sunucu, "SunucuYoneticisi", _SahteSunucuYoneticisi)

    class BasarisizAmaCalisanOrk:
        def __init__(self, ws, log):
            self._ws = ws
            self.iptal_kontrol = None

        def gorev_calistir(self, gorev, devam=False):
            # Gerçek bir FastAPI backend yaz → uygulama çalışır (ama testler başarısız)
            (self._ws / "backend.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
            )
            state = OturumState(gorev=gorev)
            state.ciktilar = {"dogrulama_gecti": "False"}  # bozuk test → başarısız
            return state

    monkeypatch.setattr(
        api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: BasarisizAmaCalisanOrk(ws, log)
    )
    istemci.post("/api/gorev", json={"gorev": "FastAPI backend yaz"})
    veri = _bekle_bitsin(istemci)

    assert veri["sonuc"]["dogrulama_gecti"] is False  # görev başarısız
    assert veri["onizleme_backend_url"] is not None  # ama önizleme yine de açık
    assert any("uygulama çalışıyor" in s for s in veri["log"])


def test_takip_ayni_klasorde_baglamla_calisir(istemci, monkeypatch, tmp_path):
    """Takip: aynı klasör + bağlam önsözü (dosyalar/geçmiş) + tip koruması."""
    monkeypatch.setenv("FCC_WORKSPACE", str(tmp_path))
    alinan: dict = {}

    class KaydediciOrk(SahteOrkestrator):
        def __init__(self, ws, log):
            super().__init__(log)
            self.ws = ws

        def gorev_calistir(self, gorev, devam=False):
            alinan.setdefault("gorevler", []).append(gorev)
            alinan.setdefault("klasorler", []).append(str(self.ws))
            alinan["tip"] = getattr(self, "_dogrulama_tipi", None)
            (self.ws / "index.html").write_text("<html></html>", encoding="utf-8")
            return super().gorev_calistir(gorev, devam)

    monkeypatch.setattr(
        api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: KaydediciOrk(ws, log)
    )

    # 1) İlk görev (fullstack tetikler) → yeni klasör
    istemci.post("/api/gorev", json={"gorev": "full-stack todo uygulaması yap"})
    _bekle_bitsin(istemci)
    # 2) Takip ("rengi değiştir" — playbook tetiklemez) → AYNI klasör + önsöz + tip miras
    istemci.post("/api/gorev", json={"gorev": "arka plan rengini koyu yap", "takip": True})
    veri = _bekle_bitsin(istemci)

    assert alinan["klasorler"][0] == alinan["klasorler"][1]  # aynı klasör
    takip_gorevi = alinan["gorevler"][1]
    assert "TAKİP GÖREVİ" in takip_gorevi  # bağlam önsözü eklendi
    assert "index.html" in takip_gorevi  # mevcut dosyalar listelendi
    assert "full-stack todo" in takip_gorevi  # önceki istek geçmişte
    assert alinan["tip"] == "fullstack"  # tip ilk görevden miras
    assert len(veri["sohbet"]) == 2  # istek geçmişi büyüdü


def test_yeni_gorev_sohbeti_sifirlar(istemci, monkeypatch, tmp_path):
    monkeypatch.setenv("FCC_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(
        api, "ORKESTRATOR_FABRIKASI", lambda ws, ex, log: SahteOrkestrator(log)
    )
    istemci.post("/api/gorev", json={"gorev": "ilk proje"})
    _bekle_bitsin(istemci)
    istemci.post("/api/gorev", json={"gorev": "yepyeni proje"})  # takip DEĞİL
    veri = _bekle_bitsin(istemci)
    assert [s["istek"] for s in veri["sohbet"]] == ["yepyeni proje"]


def test_onizle_html_canli_backende_yonlendirir(istemci, tmp_path):
    """Canlı önizleme backend'i varken /onizle/*.html oraya redirect eder."""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    api.DURUM.klasor_yolu = tmp_path
    api.DURUM.onizleme_backend_url = "http://localhost:54321"
    try:
        y = istemci.get("/onizle/index.html", follow_redirects=False)
        assert y.status_code in (302, 307)
        assert y.headers["location"] == "http://localhost:54321"
        # HTML olmayan dosyalar yönlendirilmez (statik servis sürer)
        (tmp_path / "notlar.txt").write_text("x", encoding="utf-8")
        y2 = istemci.get("/onizle/notlar.txt", follow_redirects=False)
        assert y2.status_code == 200
    finally:
        api.DURUM.onizleme_backend_url = None
        api.DURUM.klasor_yolu = None


def _mini_git_repo(tmp_path):
    """İki commit'li minik bir repo: geri-al/diff testleri için."""
    import subprocess

    def git(*a):
        subprocess.run(
            ["git", *a], cwd=tmp_path, check=True, capture_output=True, text=True
        )

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("ilk", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "ilk")
    (tmp_path / "a.txt").write_text("ikinci", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "degisiklik")


def test_degisiklikler_son_commit_diffini_doner(istemci, tmp_path):
    _mini_git_repo(tmp_path)
    api.DURUM.klasor_yolu = tmp_path
    try:
        y = istemci.get("/api/degisiklikler")
        assert y.status_code == 200
        assert "degisiklik" in y.text and "a.txt" in y.text
    finally:
        api.DURUM.klasor_yolu = None


def test_geri_al_son_commiti_geri_alir(istemci, tmp_path, monkeypatch):
    _mini_git_repo(tmp_path)
    api.DURUM.klasor_yolu = tmp_path
    api.DURUM.calisiyor = False
    # Önizleme yeniden başlatmayı sahtele (gerçek sunucu açılmasın)
    monkeypatch.setattr(api, "_onizleme_backendini_baslat", lambda ws: None)
    try:
        y = istemci.post("/api/geri-al")
        assert y.status_code == 200
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "ilk"  # revert etti
    finally:
        api.DURUM.klasor_yolu = None


def test_geri_al_gorev_calisirken_reddedilir(istemci, tmp_path):
    _mini_git_repo(tmp_path)
    api.DURUM.klasor_yolu = tmp_path
    api.DURUM.calisiyor = True
    try:
        assert istemci.post("/api/geri-al").status_code == 409
    finally:
        api.DURUM.calisiyor = False
        api.DURUM.klasor_yolu = None


def test_onizleme_backendi_fastapi_yoksa_atlar(tmp_path, monkeypatch):
    from orchestrator import sunucu

    monkeypatch.setattr(sunucu, "SunucuYoneticisi", _SahteSunucuYoneticisi)
    (tmp_path / "not.txt").write_text("x", encoding="utf-8")

    api._onizleme_backendini_baslat(tmp_path)  # FastAPI yok → sessizce atlar
    assert api.DURUM.onizleme_backend_url is None
