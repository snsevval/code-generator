"""Faz 4 — Proje orkestratörü testleri (sahte LLM istemcisiyle, ağsız).

Çalıştırma:
    uv run pytest tests/test_proje.py -v
"""

from __future__ import annotations

import json

import pytest

from orchestrator.agents import BASARI_ISARETI, BASARISIZLIK_ISARETI
from orchestrator.loop import Orkestrator, OrkestrasyonHatasi
from orchestrator.proje import ProjeOrkestratoru, _json_dizisi_ayikla
from orchestrator.state import ProjeState

from tests.test_orchestrator import FakeIstemci, metin_cevap


def proje_kur(tmp_path, senaryo):
    istemci = FakeIstemci(senaryo)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    ork = Orkestrator(ws, istemci=istemci, state_yolu=tmp_path / "ic.json", log=False)
    proje = ProjeOrkestratoru(ws, orkestrator=ork, state_klasoru=tmp_path / "st", log=False)
    return proje, istemci


def bolme_cevabi(*gorevler: str) -> dict:
    veri = [{"id": i + 1, "gorev": g, "kabul": f"{g} çalışsın"} for i, g in enumerate(gorevler)]
    return metin_cevap(json.dumps(veri, ensure_ascii=False))


def ic_dongu(gecti: bool = True) -> list[dict]:
    """Tek alt görevin iç döngüsü: planner→codegen→validator→reviewer."""
    isaret = BASARI_ISARETI if gecti else BASARISIZLIK_ISARETI
    cevaplar = [
        metin_cevap("plan"),
        metin_cevap("kodu yazdım"),
        metin_cevap(isaret),
    ]
    if not gecti:
        # başarısızsa debugger↔validator 3 tur döner, sonra reviewer
        for _ in range(3):
            cevaplar += [metin_cevap("düzeltme"), metin_cevap(BASARISIZLIK_ISARETI)]
    cevaplar.append(metin_cevap("rapor"))
    return cevaplar


# --- JSON ayıklama ---


def test_json_ayikla_cit_toleransli():
    metin = 'Alt görevler şunlar:\n```json\n[{"id": 1, "gorev": "a"}]\n```'
    assert _json_dizisi_ayikla(metin) == [{"id": 1, "gorev": "a"}]


@pytest.mark.parametrize(
    "bozuk",
    ["hiç json yok", "[]", '[{"id": 1}]', '[{"gorev": ""}]', "[{bozuk"],
)
def test_json_ayikla_gecersizleri_reddeder(bozuk):
    with pytest.raises(OrkestrasyonHatasi):
        _json_dizisi_ayikla(bozuk)


# --- Zincir ---


def test_mutlu_yol_iki_alt_gorev(tmp_path):
    senaryo = [bolme_cevabi("modeli yaz", "cli yaz")] + ic_dongu() + ic_dongu()
    proje, istemci = proje_kur(tmp_path, senaryo)

    state = proje.hedef_calistir("küçük araç yap")

    assert [a["durum"] for a in state.alt_gorevler] == ["basarili", "basarili"]
    assert all(a["ozet"] == "kodu yazdım" for a in state.alt_gorevler)
    # İkinci alt görevin girdisinde birincinin özeti taşınmalı
    ikinci_girdi = istemci.istekler[5]["messages"][0]["content"]
    assert "modeli yaz: kodu yazdım" in ikinci_girdi
    assert "Workspace'teki mevcut dosyalar" in ikinci_girdi


def test_basarisiz_alt_gorev_zinciri_durdurur(tmp_path):
    senaryo = [bolme_cevabi("a", "b", "c")] + ic_dongu() + ic_dongu(gecti=False)
    proje, _ = proje_kur(tmp_path, senaryo)

    state = proje.hedef_calistir("hedef")

    assert [a["durum"] for a in state.alt_gorevler] == ["basarili", "basarisiz", "bekliyor"]


def test_devam_basarili_alt_gorevleri_atlar(tmp_path):
    senaryo = [bolme_cevabi("a", "b")] + ic_dongu() + ic_dongu(gecti=False)
    proje, _ = proje_kur(tmp_path, senaryo)
    proje.hedef_calistir("hedef")

    # Devamda yalnızca kalan (başarısız) alt görev koşulmalı; bölme tekrarlanmaz.
    # İç döngü state'i temizlenir ki alt görev baştan denensin.
    for f in (tmp_path / "st").glob("alt_*.json"):
        f.unlink()
    proje2, istemci2 = proje_kur(tmp_path, ic_dongu())
    proje2.state_klasoru = proje.state_klasoru

    state = proje2.hedef_calistir("hedef", devam=True)

    assert [a["durum"] for a in state.alt_gorevler] == ["basarili", "basarili"]
    # decomposer çağrılmadı: ilk istek doğrudan planner'a gitmiş olmalı
    assert "PLANNER" in istemci2.istekler[0]["system"]


def test_gorev_metni_sabitlenir_ve_devamda_ayni_kalir(tmp_path):
    """Alt görev metni ilk üretimde state'e yazılır; workspace değişse de
    devamda aynı metin kullanılır (iç-döngü devamının ön koşulu)."""
    senaryo = [bolme_cevabi("a")] + ic_dongu(gecti=False)
    proje, _ = proje_kur(tmp_path, senaryo)
    state1 = proje.hedef_calistir("hedef")
    kayitli_metin = state1.alt_gorevler[0]["gorev_metni"]
    assert "Workspace'teki mevcut dosyalar" in kayitli_metin

    # Workspace'e dosya eklense bile devamda kayıtlı metin değişmemeli
    (proje.ork.executor.workspace / "sonradan.txt").write_text("x", encoding="utf-8")
    for f in (tmp_path / "st").glob("alt_*.json"):
        f.unlink()
    proje2, istemci2 = proje_kur(tmp_path, ic_dongu())
    proje2.state_klasoru = proje.state_klasoru
    proje2.hedef_calistir("hedef", devam=True)

    assert istemci2.istekler[0]["messages"][0]["content"].endswith(
        kayitli_metin.split("Görev: ")[-1]
    ) or kayitli_metin in istemci2.istekler[0]["messages"][0]["content"]


def test_tikanan_alt_gorev_zinciri_duzgun_durdurur(tmp_path):
    class TikananOrk:
        class executor:  # list_files için asgari arayüz
            @staticmethod
            def list_files():
                from orchestrator.tool_executor import ToolSonucu

                return ToolSonucu(True, "(klasör boş)")

        state_yolu = None

        def ajan_calistir(self, ajan, metin):
            return '[{"id": 1, "gorev": "tek iş", "kabul": "olsun"}]'

        def gorev_calistir(self, gorev, devam=False):
            raise OrkestrasyonHatasi("codegen ajanı 25 tool turunda görevi bitiremedi")

    proje = ProjeOrkestratoru(tmp_path, orkestrator=TikananOrk(), state_klasoru=tmp_path / "st", log=False)
    state = proje.hedef_calistir("hedef")  # exception yükseltmemeli

    assert state.alt_gorevler[0]["durum"] == "basarisiz"
    assert "tıkandı" in state.alt_gorevler[0]["ozet"]
    # State diske düzgün yazılmış olmalı
    assert ProjeState.yukle(proje.proje_state_yolu).alt_gorevler[0]["durum"] == "basarisiz"


def test_farkli_hedef_sifirdan_bolunur(tmp_path):
    eski = ProjeState(hedef="eski hedef", alt_gorevler=[{"id": 1, "gorev": "x", "kabul": "", "durum": "basarili", "ozet": ""}])
    proje, istemci = proje_kur(tmp_path, [bolme_cevabi("yeni iş")] + ic_dongu())
    eski.kaydet(proje.proje_state_yolu)

    state = proje.hedef_calistir("yepyeni hedef", devam=True)

    assert state.hedef == "yepyeni hedef"
    assert "DECOMPOSER" in istemci.istekler[0]["system"]
