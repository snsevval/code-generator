"""Faz 2 — Orkestratör birim testleri (ağsız, sahte LLM istemcisiyle).

Çalıştırma:
    uv run pytest tests/test_orchestrator.py -v
"""

from __future__ import annotations

import pytest

from orchestrator.agents import AJANLAR, BASARI_ISARETI, BASARISIZLIK_ISARETI
from orchestrator.loop import MAX_DEBUG_TURU, Orkestrator, OrkestrasyonHatasi
from orchestrator.state import OturumState


def metin_cevap(metin: str) -> dict:
    return {"content": [{"type": "text", "text": metin}], "stop_reason": "end_turn"}


def tool_cevap(ad: str, girdi: dict, blok_id: str = "tu_1") -> dict:
    return {
        "content": [{"type": "tool_use", "id": blok_id, "name": ad, "input": girdi}],
        "stop_reason": "tool_use",
    }


class FakeIstemci:
    """Sıradaki cevabı senaryodan döndüren sahte LLM istemcisi."""

    def __init__(self, senaryo: list[dict]):
        self.senaryo = list(senaryo)
        self.istekler: list[dict] = []  # gönderilen isteklerin kaydı

    def mesaj_gonder(self, **kwargs) -> dict:
        self.istekler.append(kwargs)
        if not self.senaryo:
            raise AssertionError("senaryo tükendi ama istek gelmeye devam ediyor")
        return self.senaryo.pop(0)


def orkestrator_kur(tmp_path, senaryo):
    istemci = FakeIstemci(senaryo)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    ork = Orkestrator(
        ws, istemci=istemci, state_yolu=tmp_path / "state.json", log=False
    )
    return ork, istemci


# --- Ajan tool döngüsü ---


def test_ajan_tool_dongusu_calistirir_ve_geri_besler(tmp_path):
    senaryo = [
        tool_cevap("write_file", {"path": "a.txt", "content": "merhaba"}),
        metin_cevap("a.txt dosyasını yazdım."),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)

    cikti = ork.ajan_calistir(AJANLAR["codegen"], "a.txt oluştur")

    assert cikti == "a.txt dosyasını yazdım."
    assert (ork.executor.workspace / "a.txt").read_text(encoding="utf-8") == "merhaba"
    # İkinci istekte tool_result geri beslenmiş olmalı
    son_mesaj = istemci.istekler[1]["messages"][-1]
    assert son_mesaj["content"][0]["type"] == "tool_result"
    assert son_mesaj["content"][0]["is_error"] is False


def test_ajan_hatali_tool_sonucu_is_error_ile_doner(tmp_path):
    senaryo = [
        tool_cevap("read_file", {"path": "../kacak.txt"}),
        metin_cevap("olmadı"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork.ajan_calistir(AJANLAR["codegen"], "oku")

    sonuc = istemci.istekler[1]["messages"][-1]["content"][0]
    assert sonuc["is_error"] is True
    assert "HATA" in sonuc["content"]


def test_ajan_izinsiz_araci_alamaz(tmp_path):
    ork, istemci = orkestrator_kur(tmp_path, [metin_cevap("plan")])
    ork.ajan_calistir(AJANLAR["planner"], "planla")

    gonderilen_araclar = {t["name"] for t in istemci.istekler[0]["tools"]}
    assert gonderilen_araclar == {"list_files", "read_file"}  # planner yalnızca okuyabilir


def test_validator_mevcut_dosyayi_degistiremez(tmp_path):
    senaryo = [
        tool_cevap("write_file", {"path": "kod.py", "content": "yeniden yazdım"}),
        metin_cevap("olmadı"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    (ork.executor.workspace / "kod.py").write_text("orijinal", encoding="utf-8")

    ork.ajan_calistir(AJANLAR["validator"], "doğrula")

    # Dosya değişmemiş olmalı, model hatayla bilgilendirilmeli
    assert (ork.executor.workspace / "kod.py").read_text(encoding="utf-8") == "orijinal"
    sonuc = istemci.istekler[1]["messages"][-1]["content"][0]
    assert sonuc["is_error"] is True
    assert "değiştiremez" in sonuc["content"]


def test_validator_yeni_dosya_yazabilir(tmp_path):
    senaryo = [
        tool_cevap("write_file", {"path": "test_yeni.py", "content": "assert True"}),
        metin_cevap("test ekledim"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork.ajan_calistir(AJANLAR["validator"], "doğrula")

    assert (ork.executor.workspace / "test_yeni.py").is_file()
    assert istemci.istekler[1]["messages"][-1]["content"][0]["is_error"] is False


def test_eski_arac_ciktilari_kirpilir(tmp_path):
    uzun = "X" * 5000
    senaryo = [
        tool_cevap("read_file", {"path": "a.txt"}, "tu_1"),
        tool_cevap("read_file", {"path": "a.txt"}, "tu_2"),
        metin_cevap("bitti"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    (ork.executor.workspace / "a.txt").write_text(uzun, encoding="utf-8")

    ork.ajan_calistir(AJANLAR["codegen"], "oku oku")

    # 3. istekte: ilk tool_result kırpılmış, son (en güncel) tam olmalı
    mesajlar = istemci.istekler[2]["messages"]
    ilk_sonuc = mesajlar[2]["content"][0]["content"]
    son_sonuc = mesajlar[4]["content"][0]["content"]
    assert "kırpıldı" in ilk_sonuc
    assert len(ilk_sonuc) < 1000
    assert son_sonuc == uzun


def test_ajan_sonsuz_tool_dongusunde_durdurulur(tmp_path):
    senaryo = [tool_cevap("read_file", {"path": "x"})] * 100
    ork, _ = orkestrator_kur(tmp_path, senaryo)
    with pytest.raises(OrkestrasyonHatasi, match="bitiremedi"):
        ork.ajan_calistir(AJANLAR["codegen"], "dur durak bilme")


# --- Ana akış ---


def test_mutlu_yol_ajan_sirasi(tmp_path):
    senaryo = [
        metin_cevap("1. adım: a.py yaz"),  # planner
        metin_cevap("a.py yazıldı"),  # codegen
        metin_cevap(f"testler geçti\n{BASARI_ISARETI}"),  # validator
        metin_cevap("kod temiz görünüyor"),  # reviewer
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("küçük görev")

    roller = [i["system"] for i in istemci.istekler]
    assert "PLANNER" in roller[0]
    assert "CODEGEN" in roller[1]
    assert "VALIDATOR" in roller[2]
    assert "REVIEWER" in roller[3]
    assert state.ciktilar["dogrulama_gecti"] == "True"
    assert state.debug_turu == 0


def test_basarisiz_dogrulama_debugger_tetikler(tmp_path):
    senaryo = [
        metin_cevap("plan"),  # planner
        metin_cevap("kod yazıldı"),  # codegen
        metin_cevap(f"hata var\n{BASARISIZLIK_ISARETI}"),  # validator (1.)
        metin_cevap("hatayı düzelttim"),  # debugger
        metin_cevap(f"şimdi geçti\n{BASARI_ISARETI}"),  # validator (2.)
        metin_cevap("rapor"),  # reviewer
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("görev")

    assert state.debug_turu == 1
    assert state.ciktilar["dogrulama_gecti"] == "True"
    assert "DEBUGGER" in istemci.istekler[3]["system"]


def test_debug_turu_siniri(tmp_path):
    senaryo = [metin_cevap("plan"), metin_cevap("kod")]
    # validator hep başarısız + araya debugger: MAX tur boyunca
    senaryo.append(metin_cevap(BASARISIZLIK_ISARETI))
    for _ in range(MAX_DEBUG_TURU):
        senaryo.append(metin_cevap("düzeltme denemesi"))  # debugger
        senaryo.append(metin_cevap(BASARISIZLIK_ISARETI))  # validator yine kötü
    senaryo.append(metin_cevap("rapor"))  # reviewer yine de koşar

    ork, _ = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("inatçı görev")

    assert state.debug_turu == MAX_DEBUG_TURU
    assert state.ciktilar["dogrulama_gecti"] == "False"
    assert "reviewer" in state.ciktilar


def test_isaretsiz_validator_ciktisi_hata(tmp_path):
    senaryo = [
        metin_cevap("plan"),
        metin_cevap("kod"),
        metin_cevap("bir şeyler oldu ama işaret koymadım"),
    ]
    ork, _ = orkestrator_kur(tmp_path, senaryo)
    with pytest.raises(OrkestrasyonHatasi, match="işareti yok"):
        ork.gorev_calistir("görev")


# --- State / devam ---


def test_state_kaydedilir_ve_devam_atlar(tmp_path):
    senaryo = [
        metin_cevap("plan"),
        metin_cevap("kod"),
        metin_cevap(BASARI_ISARETI),
        metin_cevap("rapor"),
    ]
    ork, _ = orkestrator_kur(tmp_path, senaryo)
    ork.gorev_calistir("görev")

    # Aynı görevle devam: hiçbir yeni LLM çağrısı gerekmemeli
    # (dogrulama_gecti yeniden hesaplanırken validator çıktısı kayıttan okunur)
    ork2, istemci2 = orkestrator_kur(tmp_path, [])
    ork2.state_yolu = ork.state_yolu
    state = ork2.gorev_calistir("görev", devam=True)
    assert istemci2.istekler == []
    assert state.tamamlanan == ["planner", "codegen", "validator", "reviewer"]


def test_farkli_gorev_devam_etmez(tmp_path):
    eski = OturumState(gorev="eski görev")
    eski.asama_bitti("planner", "eski plan")
    yol = tmp_path / "state.json"
    eski.kaydet(yol)

    yuklenen = OturumState.yukle(yol)
    assert yuklenen is not None and yuklenen.gorev == "eski görev"

    senaryo = [
        metin_cevap("yeni plan"),
        metin_cevap("kod"),
        metin_cevap(BASARI_ISARETI),
        metin_cevap("rapor"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork.state_yolu = yol
    state = ork.gorev_calistir("yepyeni görev", devam=True)
    # görev farklı olduğu için sıfırdan başlamalı
    assert state.ciktilar["planner"] == "yeni plan"
    assert len(istemci.istekler) == 4


def test_bozuk_state_dosyasi_yok_sayilir(tmp_path):
    yol = tmp_path / "state.json"
    yol.write_text("{bozuk json", encoding="utf-8")
    assert OturumState.yukle(yol) is None
