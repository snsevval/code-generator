"""Faz 2 — Orkestratör birim testleri (ağsız, sahte LLM istemcisiyle).

Çalıştırma:
    uv run pytest tests/test_orchestrator.py -v
"""

from __future__ import annotations

import pytest

from orchestrator.agents import AJANLAR, BASARI_ISARETI, BASARISIZLIK_ISARETI
from orchestrator.loop import (
    MAX_DEBUG_TURU,
    IptalEdildi,
    Orkestrator,
    OrkestrasyonHatasi,
)
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


def validator_cevaplari(karar_metni: str) -> list[dict]:
    """Kanıt şartını sağlayan validator cevabı: bir araç çağrısı + karar."""
    return [tool_cevap("list_files", {}, "tv_kanit"), metin_cevap(karar_metni)]


def orkestrator_kur(tmp_path, senaryo):
    istemci = FakeIstemci(senaryo)
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    ork = Orkestrator(
        ws, istemci=istemci, state_yolu=tmp_path / "state.json", log=False, git=False
    )
    return ork, istemci


def test_iptal_gorevi_temiz_durdurur(tmp_path):
    # Kullanıcı iptal edince (iptal_kontrol True) görev IptalEdildi ile durur —
    # sonsuz/yanlış görevde takılıp kalmadan yeni projeye geçilebilsin
    senaryo = [metin_cevap("plan")] * 10  # planner'a kadar gelmemeli bile
    ork, _ = orkestrator_kur(tmp_path, senaryo)
    ork.iptal_kontrol = lambda: True  # anında iptal
    with pytest.raises(IptalEdildi):
        ork.gorev_calistir("yanlış görev")


def test_iptal_yoksa_normal_calisir(tmp_path):
    # iptal_kontrol False dönerse hiçbir etkisi olmamalı (normal akış)
    senaryo = (
        [metin_cevap("plan")]
        + [tool_cevap("write_file", {"path": "a.py", "content": "x=1"}, "c1"),
           metin_cevap("yazdım")]
        + validator_cevaplari(BASARI_ISARETI)
        + [metin_cevap("rapor")]
    )
    ork, _ = orkestrator_kur(tmp_path, senaryo)
    ork.iptal_kontrol = lambda: False
    state = ork.gorev_calistir("normal görev")
    assert state.ciktilar["dogrulama_gecti"] == "True"


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


def test_string_tool_input_dict_e_normalize_edilir(tmp_path):
    # Kimi NIM/OpenRouter kod modelleri tool_use.input'u JSON string döndürüyor;
    # orkestratör bunu dict'e çevirip normal işlemeli (yoksa AttributeError).
    senaryo = [
        tool_cevap("write_file", '{"path": "a.txt", "content": "merhaba"}'),
        metin_cevap("yazdım"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)

    ork.ajan_calistir(AJANLAR["codegen"], "a.txt oluştur")

    assert (ork.executor.workspace / "a.txt").read_text(encoding="utf-8") == "merhaba"
    assert istemci.istekler[1]["messages"][-1]["content"][0]["is_error"] is False


def test_bozuk_string_tool_input_cokmeden_bos_dict_olur(tmp_path):
    # Geçersiz JSON string gelirse: çökme yok, boş dict'e düşer, araç düzgün hata verir
    senaryo = [
        tool_cevap("write_file", "{bozuk json"),
        metin_cevap("olmadı"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)

    ork.ajan_calistir(AJANLAR["codegen"], "yaz")

    # AttributeError fırlamamalı; araç zorunlu alan eksikliğiyle hata döndürmeli
    assert istemci.istekler[1]["messages"][-1]["content"][0]["is_error"] is True


def test_ajan_izinsiz_araci_alamaz(tmp_path):
    ork, istemci = orkestrator_kur(tmp_path, [metin_cevap("plan")])
    ork.ajan_calistir(AJANLAR["planner"], "planla")

    gonderilen_araclar = {t["name"] for t in istemci.istekler[0]["tools"]}
    # planner yalnızca okuma/arama yapabilir
    assert gonderilen_araclar == {"list_files", "search_files", "read_file"}


def test_reviewer_salt_okunur_kisa_ve_json(tmp_path):
    rev = AJANLAR["reviewer"]
    # Salt-okunur: yazma/çalıştırma aracı yok
    assert set(rev.araclar) == {"list_files", "read_file"}
    assert "write_file" not in rev.araclar and "run_shell" not in rev.araclar
    # Kısa: çıktı token sınırı var (2-4k)
    assert rev.max_tokens is not None and 2000 <= rev.max_tokens <= 4000
    # ajan_calistir max_tokens'ı mesaj_gonder'e geçirir; prompt JSON+kanıt ister
    ork, istemci = orkestrator_kur(
        tmp_path, [metin_cevap('{"approved": true, "issues": [], "evidence": []}')]
    )
    ork.ajan_calistir(rev, "incele")
    assert istemci.istekler[0]["max_tokens"] == rev.max_tokens
    sistem = istemci.istekler[0]["system"]
    assert "approved" in sistem and "evidence" in sistem and "KANIT" in sistem.upper()


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


@pytest.mark.parametrize(
    "komut",
    ["del notlar.json", "rm -rf klasor", "move a.txt b.txt", "echo x > mevcut.txt", "DEL /f a.py"],
)
def test_validator_yikici_kabuk_komutu_engellenir(tmp_path, komut):
    senaryo = [tool_cevap("run_shell", {"command": komut}), metin_cevap("olmadı")]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    (ork.executor.workspace / "notlar.json").write_text("[]", encoding="utf-8")

    ork.ajan_calistir(AJANLAR["validator"], "doğrula")

    sonuc = istemci.istekler[1]["messages"][-1]["content"][0]
    assert sonuc["is_error"] is True
    assert "silemez" in sonuc["content"]
    assert (ork.executor.workspace / "notlar.json").exists()


def test_validator_test_komutlari_calisir(tmp_path):
    senaryo = [
        tool_cevap("run_shell", {"command": "python -c \"print('pytest gibi')\""}),
        metin_cevap("tamam"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork.ajan_calistir(AJANLAR["validator"], "doğrula")
    assert istemci.istekler[1]["messages"][-1]["content"][0]["is_error"] is False


def test_debugger_kabuk_kisiti_yok(tmp_path):
    # Kısıt yalnızca dosya değiştiremeyen roller için; debugger silme yapabilir
    senaryo = [tool_cevap("run_shell", {"command": "del eski.txt"}), metin_cevap("ok")]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    (ork.executor.workspace / "eski.txt").write_text("x", encoding="utf-8")
    ork.ajan_calistir(AJANLAR["debugger"], "düzelt")
    sonuc = istemci.istekler[1]["messages"][-1]["content"][0]
    assert "silemez" not in sonuc["content"]


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
    senaryo = (
        [
            metin_cevap("1. adım: a.py yaz"),  # planner
            metin_cevap("a.py yazıldı"),  # codegen
        ]
        + validator_cevaplari(f"testler geçti\n{BASARI_ISARETI}")
        + [metin_cevap("kod temiz görünüyor")]  # reviewer
    )
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("küçük görev")

    roller = [i["system"] for i in istemci.istekler]
    assert "PLANNER" in roller[0]
    assert "CODEGEN" in roller[1]
    assert "VALIDATOR" in roller[2] and "VALIDATOR" in roller[3]
    assert "REVIEWER" in roller[4]
    assert state.ciktilar["dogrulama_gecti"] == "True"
    assert state.debug_turu == 0


def test_codegen_arac_kullanip_yazmazsa_durtuyle_tekrar(tmp_path):
    # Gözlenen hata: codegen list_files çağırıp hiç yazmadan metinle durdu → dürtü
    senaryo = (
        [metin_cevap("plan")]
        + [tool_cevap("list_files", {}, "cg1"), metin_cevap("baktım, boş")]  # codegen 1: araç var, yazma yok
        + [tool_cevap("write_file", {"path": "kod.py", "content": "x = 1"}, "cg2"), metin_cevap("yazdım")]  # dürtü sonrası
        + validator_cevaplari(BASARI_ISARETI)
        + [metin_cevap("rapor")]
    )
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("görev")

    assert (ork.executor.workspace / "kod.py").is_file()
    # FakeIstemci mesaj listesini referansla saklar; distinct çağrı = distinct liste kimliği.
    # Nudge ile başlayan kaç AYRI codegen çağrısı olduğunu böyle sayarız.
    durtulen_cagrilar = {
        id(i["messages"])
        for i in istemci.istekler
        if isinstance(i["messages"][0]["content"], str)
        and "HİÇ dosya yazmadın" in i["messages"][0]["content"]
    }
    assert len(durtulen_cagrilar) == 1  # tam bir kez dürtüldü
    assert state.ciktilar["dogrulama_gecti"] == "True"


def test_codegen_yazdiysa_durtu_yok(tmp_path):
    # Codegen ilk denemede dosya yazdıysa dürtü tetiklenmemeli
    senaryo = (
        [metin_cevap("plan")]
        + [tool_cevap("write_file", {"path": "kod.py", "content": "x = 1"}, "c1"), metin_cevap("yazdım")]
        + validator_cevaplari(BASARI_ISARETI)
        + [metin_cevap("rapor")]
    )
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("görev")

    durtus = [
        i for i in istemci.istekler
        if isinstance(i["messages"][0]["content"], str)
        and "HİÇ dosya yazmadın" in i["messages"][0]["content"]
    ]
    assert durtus == []
    assert state.ciktilar["dogrulama_gecti"] == "True"


def test_backend_codegen_yalniz_dosya_araclari(tmp_path):
    # dogrulama_tipi="backend" → codegen'e run_shell/start_server/check_page VERİLMEZ
    senaryo = [
        tool_cevap("write_file", {"path": "backend.py", "content": "x = 1"}),
        metin_cevap("yazdım"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork._dogrulama_tipi = "backend"
    ork.ajan_calistir(AJANLAR["codegen"], "backend yaz")

    gonderilen = {t["name"] for t in istemci.istekler[0]["tools"]}
    assert gonderilen == {"list_files", "search_files", "read_file", "write_file", "edit_file"}
    assert "run_shell" not in gonderilen
    assert "start_server" not in gonderilen
    assert "check_page" not in gonderilen
    assert "araçların YOK" in istemci.istekler[0]["system"]  # backend notu eklenmiş


def test_backend_debugger_yalniz_dosya_araclari(tmp_path):
    # Debugger da file-only: run_shell'i yok → pytest koşamaz → docker halüsinasyonu imkansız
    senaryo = [
        tool_cevap("edit_file", {"path": "kod.py", "eski_metin": "a", "yeni_metin": "b"}),
        metin_cevap("düzelttim"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    (ork.executor.workspace / "kod.py").write_text("a", encoding="utf-8")
    ork._dogrulama_tipi = "fullstack"
    ork.ajan_calistir(AJANLAR["debugger"], "düzelt")

    gonderilen = {t["name"] for t in istemci.istekler[0]["tools"]}
    assert gonderilen == {"list_files", "search_files", "read_file", "write_file", "edit_file"}
    assert "run_shell" not in gonderilen
    assert "yeniden üretmene gerek yok" in istemci.istekler[0]["system"] or \
           "yeniden" in istemci.istekler[0]["system"]  # debugger notu eklendi


def test_takip_codegen_yazmadiysa_basarili_sayilmaz(tmp_path):
    # Canlıda: takipte codegen hiçbir dosyayı değiştirmedi ama eski proje geçtiği
    # için 'BAŞARILI' raporlandı (login isteği yutuldu). Kural: takipte değişiklik
    # yoksa doğrulamaya gitmeden BAŞARISIZ sayılır → Debugger'a net gerekçe düşer.
    senaryo = (
        [metin_cevap("plan")]
        + [tool_cevap("list_files", {}, "c1"), metin_cevap("baktım")]  # codegen: araç var, yazma yok
        + [tool_cevap("list_files", {}, "c2"), metin_cevap("yine baktım")]  # dürtü sonrası da yazmadı
        + [tool_cevap("write_file", {"path": "index.html", "content": "<html>login</html>"}, "d1"),
           metin_cevap("login ekledim")]  # debugger değişikliği uygular
        + validator_cevaplari(BASARI_ISARETI)  # yeniden doğrulama geçer
        + [metin_cevap("rapor")]
    )
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork._takip = True
    state = ork.gorev_calistir("giriş sayfası ekle")

    assert state.debug_turu == 1  # sahte başarı yerine debugger devreye girdi
    assert state.ciktilar["dogrulama_gecti"] == "True"
    assert (ork.executor.workspace / "index.html").is_file()  # değişiklik gerçekten yapıldı
    # Debugger'a giden görev net gerekçeyi içermeli
    debugger_gorevi = next(
        i["messages"][0]["content"] for i in istemci.istekler
        if isinstance(i["messages"][0]["content"], str)
        and "UYGULANMADI" in i["messages"][0]["content"]
    )
    assert "giriş sayfası ekle" in debugger_gorevi


def test_takip_codegen_yazdiysa_normal_akis(tmp_path):
    # Takipte codegen değişiklik yaptıysa kural devreye girmez, normal doğrulama koşar
    senaryo = (
        [metin_cevap("plan")]
        + [tool_cevap("edit_file", {"path": "a.txt", "eski_metin": "x", "yeni_metin": "y"}, "c1"),
           metin_cevap("düzenledim")]
        + validator_cevaplari(BASARI_ISARETI)
        + [metin_cevap("rapor")]
    )
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    (ork.executor.workspace / "a.txt").write_text("x", encoding="utf-8")
    ork._takip = True
    state = ork.gorev_calistir("a'yı y yap")

    assert state.debug_turu == 0
    assert state.ciktilar["dogrulama_gecti"] == "True"


def test_backend_disi_codegen_tam_arac_seti(tmp_path):
    # frontend/None → codegen tam araç setini (check_page, start_server) korur
    senaryo = [
        tool_cevap("write_file", {"path": "index.html", "content": "<html></html>"}),
        metin_cevap("yazdım"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork._dogrulama_tipi = "frontend"
    ork.ajan_calistir(AJANLAR["codegen"], "sayfa yap")

    gonderilen = {t["name"] for t in istemci.istekler[0]["tools"]}
    assert "check_page" in gonderilen
    assert "start_server" in gonderilen
    assert "run_shell" in gonderilen


def test_basarisiz_dogrulama_debugger_tetikler(tmp_path):
    senaryo = (
        [metin_cevap("plan"), metin_cevap("kod yazıldı")]
        + validator_cevaplari(f"hata var\n{BASARISIZLIK_ISARETI}")  # validator (1.)
        # debugger GERÇEKTEN dosya yazar (no-op freni tetiklenmesin, gerçek düzeltme)
        + [tool_cevap("write_file", {"path": "fix.py", "content": "x=1"}, "d1"),
           metin_cevap("hatayı düzelttim")]
        + validator_cevaplari(f"şimdi geçti\n{BASARI_ISARETI}")  # validator (2.)
        + [metin_cevap("rapor")]  # reviewer
    )
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("görev")

    assert state.debug_turu == 1
    assert state.ciktilar["dogrulama_gecti"] == "True"
    assert "DEBUGGER" in istemci.istekler[4]["system"]


def test_debug_turu_siniri(tmp_path):
    senaryo = [metin_cevap("plan"), metin_cevap("kod")]
    # validator hep başarısız + araya debugger: MAX tur boyunca. Debugger HER turda bir
    # dosya yazar ki no-op freni tetiklenmesin (gerçek tükenme senaryosu test edilsin).
    senaryo += validator_cevaplari(BASARISIZLIK_ISARETI)
    for _ in range(MAX_DEBUG_TURU):
        senaryo.append(tool_cevap("write_file", {"path": "fix.py", "content": "x=1"}, "d"))
        senaryo.append(metin_cevap("düzeltme denemesi"))  # debugger dosya yazdı
        senaryo += validator_cevaplari(BASARISIZLIK_ISARETI)  # validator yine kötü

    ork, _ = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("inatçı görev")

    assert state.debug_turu == MAX_DEBUG_TURU
    assert state.ciktilar["dogrulama_gecti"] == "False"
    assert "reviewer" not in state.ciktilar  # başarısız koşuda reviewer atlanır


def test_debugger_noop_erken_cikis(tmp_path):
    # Debugger hiçbir dosyayı değiştirmezse aynı testi tekrar koşmak anlamsız →
    # 3 tur harcamadan 1 turda erken çıkılır (canlıda 3 boş tur gözlendi)
    senaryo = (
        [metin_cevap("plan")]
        + [tool_cevap("write_file", {"path": "a.py", "content": "x=1"}, "c1"),
           metin_cevap("yazdım")]
        + validator_cevaplari(BASARISIZLIK_ISARETI)  # doğrulama başarısız
        + [metin_cevap("sadece baktım, düzeltmedim")]  # debugger: HİÇ dosya yazmaz
    )
    ork, _ = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("görev")

    assert state.debug_turu == 1  # 3 değil — no-op'ta erken çıktı
    assert state.ciktilar["dogrulama_gecti"] == "False"
    assert "reviewer" not in state.ciktilar  # başarısızda reviewer atlandı


def test_eksik_dosya_durtusu_fullstack(tmp_path):
    # Fullstack'te codegen sadece backend.py yazar; index.html + test eksik →
    # doğrulamaya gitmeden isim isim dürtülür (canlıda 'sadece backend' koşusu gözlendi)
    senaryo = [
        tool_cevap("write_file",
                   {"path": "backend.py", "content": "from fastapi import FastAPI\napp=FastAPI()"}, "c1"),
        metin_cevap("backend yazdım"),
        # dürtü sonrası eksikleri yazar
        tool_cevap("write_file", {"path": "index.html", "content": "<html></html>"}, "c2"),
        tool_cevap("write_file", {"path": "test_backend.py", "content": "def test_x():\n    pass"}, "c3"),
        metin_cevap("eksikleri yazdım"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork._dogrulama_tipi = "fullstack"
    state = OturumState(gorev="g")
    ork._codegen_kos(state, "g", "plan")

    # Dürtü tetiklendi: bir istekte "eksik" geçmeli + eksik dosyalar gerçekten yazıldı
    dursozler = [
        i["messages"][0]["content"] for i in istemci.istekler
        if isinstance(i["messages"][0]["content"], str)
    ]
    assert any("eksik" in s.lower() for s in dursozler)
    assert (ork.executor.workspace / "index.html").is_file()
    assert (ork.executor.workspace / "test_backend.py").is_file()


def test_isaretsiz_validator_netlestirmeyle_cozulur(tmp_path):
    senaryo = (
        [metin_cevap("plan"), metin_cevap("kod")]
        + validator_cevaplari("her şey yolunda ama işaret koymayı unuttum")
        + [
            metin_cevap(BASARI_ISARETI),  # netleştirme cevabı
            metin_cevap("rapor"),  # reviewer
        ]
    )
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("görev")

    assert state.ciktilar["dogrulama_gecti"] == "True"
    assert state.debug_turu == 0
    # Netleştirme isteği validator rolüne gitmiş olmalı
    assert "VALIDATOR" in istemci.istekler[4]["system"]
    assert "TEK satırla" in istemci.istekler[4]["messages"][0]["content"]


def test_netlestirme_de_isaretsizse_hata(tmp_path):
    senaryo = (
        [metin_cevap("plan"), metin_cevap("kod")]
        + validator_cevaplari("işaret yok")
        + [metin_cevap("yine işaret koymuyorum")]  # netleştirme de işaretsiz
    )
    ork, _ = orkestrator_kur(tmp_path, senaryo)
    with pytest.raises(OrkestrasyonHatasi, match="işareti yok"):
        ork.gorev_calistir("görev")


# --- Kanıt şartı ---


def test_kanitsiz_validator_reddedilir_ikincide_kabul(tmp_path):
    senaryo = (
        [metin_cevap("plan"), metin_cevap("kod")]
        + [metin_cevap(BASARISIZLIK_ISARETI)]  # 1. deneme: araçsız hüküm → red
        + validator_cevaplari(BASARI_ISARETI)  # 2. deneme: kanıtlı
        + [metin_cevap("rapor")]
    )
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    state = ork.gorev_calistir("görev")

    assert state.ciktilar["dogrulama_gecti"] == "True"
    assert state.debug_turu == 0  # kanıtsız BASARISIZ debugger'ı tetiklememeli
    # Yeniden isteme mesajı gitmiş olmalı
    assert "reddedildi" in istemci.istekler[3]["messages"][0]["content"]


def test_kanitsiz_validator_iki_kez_hata(tmp_path):
    senaryo = [
        metin_cevap("plan"),
        metin_cevap("kod"),
        metin_cevap(BASARISIZLIK_ISARETI),  # araçsız
        metin_cevap(BASARI_ISARETI),  # yine araçsız
    ]
    ork, _ = orkestrator_kur(tmp_path, senaryo)
    with pytest.raises(OrkestrasyonHatasi, match="kanıt"):
        ork.gorev_calistir("görev")


# --- Tekrar kilidi ---


def test_ayni_cagri_ucuncude_bloklanir(tmp_path):
    senaryo = [
        tool_cevap("read_file", {"path": "a.txt"}, "t1"),
        tool_cevap("read_file", {"path": "a.txt"}, "t2"),
        tool_cevap("read_file", {"path": "a.txt"}, "t3"),
        metin_cevap("pes ettim"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    (ork.executor.workspace / "a.txt").write_text("içerik", encoding="utf-8")
    ork.ajan_calistir(AJANLAR["debugger"], "incele")

    # Konuşma dizisi: [görev, asst1, sonuç1, asst2, sonuç2, asst3, sonuç3]
    mesajlar = istemci.istekler[-1]["messages"]
    ikinci = mesajlar[4]["content"][0]
    ucuncu = mesajlar[6]["content"][0]
    assert ikinci["is_error"] is False  # 2. çağrı serbest
    assert ucuncu["is_error"] is True  # 3. çağrı bloklu
    assert "zaten" in ucuncu["content"]


def test_write_file_tekrar_sayacini_sifirlar(tmp_path):
    senaryo = [
        tool_cevap("run_shell", {"command": "python -c \"print(1)\""}, "t1"),
        tool_cevap("run_shell", {"command": "python -c \"print(1)\""}, "t2"),
        tool_cevap("write_file", {"path": "duzeltme.py", "content": "x = 1"}, "t3"),
        tool_cevap("run_shell", {"command": "python -c \"print(1)\""}, "t4"),
        metin_cevap("bitti"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork.ajan_calistir(AJANLAR["debugger"], "düzelt-doğrula")

    # write_file sonrası aynı komut yeniden serbest olmalı
    # Dizi: [görev, a1, s1, a2, s2, a3(write), s3, a4, s4]
    dorduncu = istemci.istekler[-1]["messages"][8]["content"][0]
    assert dorduncu["is_error"] is False
    assert "zaten" not in dorduncu["content"]


# --- Debelenme detektörü ---


def test_pespese_kabuk_uyarisi(tmp_path):
    # 5 kez üst üste run_shell (dosya yazmadan) → uyarı enjekte edilmeli
    senaryo = [tool_cevap("run_shell", {"command": f"echo {i}"}, f"t{i}") for i in range(5)]
    senaryo.append(metin_cevap("tamam"))
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork.ajan_calistir(AJANLAR["debugger"], "iş yap")

    # 5. komutun sonucunda debelenme uyarısı olmalı
    besinci_sonuc = istemci.istekler[-1]["messages"][-1]["content"][0]["content"]
    assert "keşfetmeyi bırak" in besinci_sonuc


def test_write_file_debelenme_sayacini_sifirlar(tmp_path):
    # Araya write_file girince kabuk sayacı sıfırlanır → uyarı çıkmamalı
    senaryo = [
        tool_cevap("run_shell", {"command": "echo a"}, "t1"),
        tool_cevap("run_shell", {"command": "echo b"}, "t2"),
        tool_cevap("write_file", {"path": "x.py", "content": "print(1)"}, "t3"),
        tool_cevap("run_shell", {"command": "echo c"}, "t4"),
        tool_cevap("run_shell", {"command": "echo d"}, "t5"),
        metin_cevap("bitti"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork.ajan_calistir(AJANLAR["debugger"], "iş yap")

    # Hiçbir sonuçta debelenme uyarısı olmamalı (art arda en fazla 2 kabuk)
    for istek in istemci.istekler:
        for mesaj in istek["messages"]:
            if isinstance(mesaj.get("content"), list):
                for blok in mesaj["content"]:
                    if blok.get("type") == "tool_result":
                        assert "keşfetmeyi bırak" not in blok.get("content", "")


# --- Şema uyarısı ---


def test_bilinmeyen_parametre_notu(tmp_path):
    senaryo = [
        tool_cevap("search_files", {"query": "x", "path": "a.py"}),
        metin_cevap("tamam"),
    ]
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    (ork.executor.workspace / "a.py").write_text("x = 1", encoding="utf-8")
    ork.ajan_calistir(AJANLAR["debugger"], "ara")

    sonuc = istemci.istekler[1]["messages"][-1]["content"][0]
    assert "path diye parametre yok" in sonuc["content"]
    assert "query" in sonuc["content"]  # geçerli parametreler listelenmiş


# --- State / devam ---


def test_state_kaydedilir_ve_devam_atlar(tmp_path):
    senaryo = (
        [metin_cevap("plan"), metin_cevap("kod")]
        + validator_cevaplari(BASARI_ISARETI)
        + [metin_cevap("rapor")]
    )
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

    senaryo = (
        [metin_cevap("yeni plan"), metin_cevap("kod")]
        + validator_cevaplari(BASARI_ISARETI)
        + [metin_cevap("rapor")]
    )
    ork, istemci = orkestrator_kur(tmp_path, senaryo)
    ork.state_yolu = yol
    state = ork.gorev_calistir("yepyeni görev", devam=True)
    # görev farklı olduğu için sıfırdan başlamalı
    assert state.ciktilar["planner"] == "yeni plan"
    assert len(istemci.istekler) == 5


def test_bozuk_state_dosyasi_yok_sayilir(tmp_path):
    yol = tmp_path / "state.json"
    yol.write_text("{bozuk json", encoding="utf-8")
    assert OturumState.yukle(yol) is None
