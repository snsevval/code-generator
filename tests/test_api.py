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


def test_onizle_html_sunar(istemci, tmp_path):
    (tmp_path / "sayfa.html").write_text("<h1>Merhaba</h1>", encoding="utf-8")
    (tmp_path / "veri.py").write_text("x = 1", encoding="utf-8")
    api.DURUM.klasor_yolu = tmp_path

    onizleme = istemci.get("/api/onizle", params={"ad": "sayfa.html"})
    assert onizleme.status_code == 200
    assert "text/html" in onizleme.headers["content-type"]
    assert "<h1>Merhaba</h1>" in onizleme.text

    # HTML olmayan dosya önizlenemez
    assert istemci.get("/api/onizle", params={"ad": "veri.py"}).status_code == 400
    # Path traversal
    (tmp_path.parent / "gizli.html").write_text("sır", encoding="utf-8")
    assert istemci.get("/api/onizle", params={"ad": "../gizli.html"}).status_code == 404


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
