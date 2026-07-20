"""Faz 2 — Orkestratör: agentic döngü.

Akış: Planner → Codegen → Test/Validator → (başarısızsa Debugger ↔ Validator,
en çok MAX_DEBUG_TURU tur) → Reviewer.

Her ajan kendi "tool döngüsünü" çalıştırır: model tool_use döndürdükçe araçlar
ToolExecutor ile yürütülür ve sonuçları tool_result olarak geri beslenir; model
metinle bitirince (end_turn) ajanın çıktısı alınır. Her aşamadan sonra state
diske yazılır (kesinti sonrası devam için).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from orchestrator.agents import (
    AJANLAR,
    BASARI_ISARETI,
    BASARISIZLIK_ISARETI,
    AjanTanimi,
)
from orchestrator.fullstack_runner import FullstackRunner, fastapi_uygulamasi_bul
from orchestrator.git_deposu import GitDeposu
from orchestrator.llm_client import LLMIstemcisi
from orchestrator.state import OturumState
from orchestrator.tool_executor import TOOL_TANIMLARI, ToolExecutor, ToolSonucu

MAX_TOOL_TURU = 35  # bir ajanın tek görevde yapabileceği en fazla tool turu
MAX_DEBUG_TURU = 3  # doğrulama başarısız kaldıkça en fazla kaç debugger turu
# Debelenme detektörü: dosya yazmadan üst üste bu kadar run_shell = keşif israfı
# (canlıda codegen 'echo hello'yu 6 kez deneyip 12 tur yaktı). write_file/edit_file
# sayacı sıfırlar; npm install + pytest gibi meşru diziler bu eşiği aşmaz.
MAX_PESPESE_KABUK = 5
# Token tasarrufu: en son tur hariç, geçmişteki araç çıktıları bu uzunluğa kırpılır
ESKI_ARAC_CIKTISI_KIRPMA = 400

# Dosya değiştiremeyen roller için kabuk yan-kanalı: silme/taşıma komutları ve
# yönlendirme ile dosya yazma da yasak (canlıda validator 'del notlar.json' koştu)
_YIKICI_KABUK = re.compile(
    r"(^|[\s&|;(])(del|erase|rd|rmdir|rm|move|mv|ren|rename|copy|cp)\b|>{1,2}",
    re.IGNORECASE,
)

# Aynı araç + aynı girdi bu kadar kez tekrarlanırsa çalıştırılmaz (döngü kırıcı);
# araya write_file girince sayaç sıfırlanır (düzelt-doğrula döngüsü meşrudur)
MAX_AYNI_CAGRI = 2

# Backend görevlerinde Codegen'e verilen araçlar: YALNIZCA dosya işlemleri.
# Doğrulamayı (pytest/uvicorn) deterministik Runner yaptığı için run_shell/
# start_server/check_page gereksiz — ve zayıf modelde yalnızca deşelenme zemini
# (canlıda codegen bu araçlarla kabuk/docker/sunucu deşeleyip 230k token yaktı).
# UI/frontend/fullstack'te Codegen tam araç setini korur (görsel geri-besleme gerekli).
_YALNIZ_DOSYA_ARACLARI = frozenset(
    {"list_files", "search_files", "read_file", "write_file", "edit_file"}
)
_CODEGEN_BACKEND_NOTU = (
    "\n\nÖNEMLİ (bu görev): YALNIZCA dosyaları yaz — backend.py, test_backend.py ve "
    "full-stack ise index.html (gerekirse yardımcı modüller). Testleri, sunucuyu veya "
    "tarayıcıyı SEN çalıştırma; sistem pytest'i izole koşar, backend'i başlatır ve "
    "frontend'in backend'e bağlandığını deterministik doğrular. Kabuk komutu, sunucu "
    "başlatma veya sayfa açma araçların YOK. Testleri baştan İZOLE yaz (her testten önce "
    "durumu sıfırlayan autouse fixture). Full-stack'te TEK-ORIGIN: backend index.html'i `/` "
    "kökünde servis etsin (FileResponse('index.html')) ve index.html fetch'te GÖRELİ yol "
    "kullansın (fetch('/todos')) — aynı origin, sabit port/CORS gerekmez. Kısa özetle bitir."
)
_DEBUGGER_BACKEND_NOTU = (
    "\n\nÖNEMLİ (bu görev): Sana Runner'ın DETERMİNİSTİK hata mesajı verildi — kesin, hatayı "
    "'yeniden üretmene' gerek yok. Test/sunucu/tarayıcı ÇALIŞTIRMA (araçların yok). İlgili "
    "dosyayı read_file ile aç, KÖK NEDENİ edit_file ile düzelt ve DUR — sistem yeniden "
    "doğrular. Ortam/paket/eklenti kurcalama YOK; testi/assert'i GEVŞETME — asıl KODU düzelt. "
    "Örn. 'frontend backend'e istek atmadı' ise index.html'deki fetch yolunu düzelt "
    "(göreli '/todos') veya backend index.html'i `/` kökünde servis etmiyorsa ekle."
)
_CPP_NOTU = (
    "\n\nÖNEMLİ (bu görev): YALNIZCA .cpp kaynağını (ve kısa README) yaz. Derlemeyi ve "
    "çalıştırmayı SİSTEM yapar (g++ -std=c++17 -static). Derleyici ARAMA, KURMA, run_shell "
    "ile derleme deneme — araçların yok. Pi için dosyanın en başına '#define _USE_MATH_DEFINES' "
    "yaz ya da 'std::acos(-1.0)' kullan. Derleme hatası verilirse ilgili satırı edit_file ile "
    "düzelt ve DUR — sistem yeniden derler."
)

# Şema uyarısı için: araç adı → geçerli parametre adları
_ARAC_PARAMETRELERI = {
    t["name"]: set(t["input_schema"].get("properties", {})) for t in TOOL_TANIMLARI
}


class IptalEdildi(RuntimeError):
    """Kullanıcı görevi iptal etti (işbirlikçi durdurma noktasında yakalanır)."""


class OrkestrasyonHatasi(RuntimeError):
    """Döngü ilerleyemedi (tool turu sınırı, işaretsiz doğrulama çıktısı vb.)."""


def _metin(yanit: dict) -> str:
    """Cevaptaki text bloklarını birleştirir."""
    return "\n".join(
        b.get("text", "") for b in yanit.get("content", []) if b.get("type") == "text"
    ).strip()


def _gecmisi_kirp(mesajlar: list[dict]) -> None:
    """Son mesaj hariç geçmişteki tool_result içeriklerini kısaltır.

    Model uzun araç çıktısına (dosya içeriği, test dökümü) yalnızca hemen
    sonraki turda ihtiyaç duyar; eski turlarda tam metni taşımak günlük token
    kotasını hızla tüketiyor. Kırpma kalıcıdır (mesaj listesi yerinde değişir).
    """
    for mesaj in mesajlar[:-1]:
        if mesaj.get("role") != "user" or not isinstance(mesaj.get("content"), list):
            continue
        for blok in mesaj["content"]:
            icerik = blok.get("content")
            if (
                blok.get("type") == "tool_result"
                and isinstance(icerik, str)
                and len(icerik) > ESKI_ARAC_CIKTISI_KIRPMA
            ):
                blok["content"] = (
                    icerik[:ESKI_ARAC_CIKTISI_KIRPMA] + "\n... [eski araç çıktısı kırpıldı]"
                )


class Orkestrator:
    def __init__(
        self,
        workspace: Path | str,
        istemci: LLMIstemcisi | None = None,
        executor: ToolExecutor | None = None,
        state_yolu: Path | str = ".state/oturum.json",
        log: bool | object = True,
        git: GitDeposu | None | bool = True,
        dogrulama_tipi: str | None = None,
    ):
        self.executor = executor or ToolExecutor(workspace)
        self.istemci = istemci or LLMIstemcisi()
        self.state_yolu = Path(state_yolu)
        self._log = log
        # Playbook tipi ("backend"/"fullstack"/...): "backend" ise doğrulama model
        # validator yerine deterministik FullstackRunner ile yapılır (istikrarsızlık
        # + sahte-BASARILI'yı öldürür). None ise klasik model-doğrulama akışı.
        self._dogrulama_tipi = dogrulama_tipi
        # Takip modu (aynı proje üzerinde değişiklik isteği): api.py atar. Takipte
        # eski proje zaten doğrulamadan geçtiği için, codegen HİÇBİR dosyayı
        # değiştirmeden "başarılı" raporlanabiliyordu (canlıda login isteği yutuldu).
        self._takip = False
        # Codegen koşusunda (dürtü dahil) en az bir dosya yazıldı/düzenlendi mi
        self._codegen_yazdi = False
        # Son ajan_calistir çağrısında gerçekten yürütülen araç sayısı
        # (kanıt şartı: doğrulama kararları araçsız kabul edilmez)
        self.son_arac_sayisi = 0
        # Son ajan_calistir çağrısındaki başarılı write_file/edit_file sayısı
        # (devam modunda aşama atlanırsa ajan_calistir hiç koşmaz — varsayılan şart)
        self.son_yazma_sayisi = 0
        # İşbirlikçi iptal: dışarıdan (api.py) atanan, True dönerse görevi temiz
        # durduran callable. Aşama başlarında ve tool turlarında kontrol edilir —
        # kullanıcı yanlış görevi iptal edip yeni projeye geçebilsin.
        self.iptal_kontrol: object | None = None
        # git=True: otomatik kur (FCC_GIT=0 veya git yoksa sessizce kapalı),
        # git=False/None: kapalı, GitDeposu örneği: onu kullan
        if git is True:
            self.git = GitDeposu.olustur(self.executor.workspace)
        else:
            self.git = git or None

    def _yaz(self, mesaj: str) -> None:
        # log: False → sessiz, True → stdout, çağrılabilir → callback (UI akışı için)
        if callable(self._log):
            self._log(mesaj)
        elif self._log:
            print(mesaj, flush=True)

    # --- Tek ajanın tool döngüsü ---

    def ajan_calistir(self, ajan: AjanTanimi, gorev_metni: str) -> str:
        """Ajanı, tool çağrıları çözülene dek çalıştırır; nihai metnini döndürür."""
        # Backend görevinde Codegen yalnızca dosya yazar (doğrulamayı Runner devraldı);
        # diğer tüm durumlarda ajan tam araç setini kullanır.
        araclar_adlari = ajan.araclar
        sistem = ajan.sistem_prompt
        if self._dogrulama_tipi in ("backend", "fullstack", "cpp") and ajan.ad in ("codegen", "debugger"):
            araclar_adlari = tuple(a for a in araclar_adlari if a in _YALNIZ_DOSYA_ARACLARI)
            if self._dogrulama_tipi == "cpp":
                sistem = sistem + _CPP_NOTU
            else:
                sistem = sistem + (
                    _CODEGEN_BACKEND_NOTU if ajan.ad == "codegen" else _DEBUGGER_BACKEND_NOTU
                )
        araclar = [t for t in TOOL_TANIMLARI if t["name"] in araclar_adlari]
        mesajlar: list[dict] = [{"role": "user", "content": gorev_metni}]
        self.son_arac_sayisi = 0
        self.son_yazma_sayisi = 0  # bu ajan koşusunda başarılı write_file/edit_file sayısı
        tekrar_sayaci: dict[tuple, int] = {}
        pespese_kabuk = 0  # dosya yazmadan art arda run_shell (debelenme sinyali)

        for _ in range(MAX_TOOL_TURU):
            self._iptal_mi()  # her tool turunda iptal kontrolü (uzun koşuyu da keser)
            _gecmisi_kirp(mesajlar)
            yanit = self.istemci.mesaj_gonder(
                model=ajan.model,
                system=sistem,
                tools=araclar or None,
                messages=mesajlar,
                max_tokens=ajan.max_tokens,
            )
            tool_bloklari = [
                b for b in yanit.get("content", []) if b.get("type") == "tool_use"
            ]
            if not tool_bloklari:
                return _metin(yanit)

            # Modelin cevabını olduğu gibi geçmişe ekle, araçları çalıştır,
            # sonuçları tool_result olarak geri ver
            mesajlar.append({"role": "assistant", "content": yanit["content"]})
            sonuc_bloklari = []
            for blok in tool_bloklari:
                self._yaz(f"    [{ajan.ad}] araç: {blok['name']}({blok.get('input', {})})")
                girdi = blok.get("input") or {}
                # Bazı sağlayıcılar tool_use.input'u JSON string döndürüyor (ör. kimi
                # NIM/OpenRouter kod modelleri); orkestratör dict bekler → normalize et,
                # yoksa aşağıdaki girdi.get(...) çağrıları AttributeError verir.
                if isinstance(girdi, str):
                    try:
                        girdi = json.loads(girdi)
                    except json.JSONDecodeError:
                        girdi = {}
                anahtar = (
                    blok["name"],
                    json.dumps(girdi, sort_keys=True, ensure_ascii=False, default=str),
                )
                tekrar_sayaci[anahtar] = tekrar_sayaci.get(anahtar, 0) + 1
                # Döngü kırıcı: durum değişmeden aynı çağrıyı yinelemek anlamsız
                # (canlıda debugger aynı dosyayı 7 kez okuyup 25 turu tüketti)
                if tekrar_sayaci[anahtar] > MAX_AYNI_CAGRI:
                    sonuc = ToolSonucu(
                        False,
                        f"HATA: {blok['name']} aracını aynı girdiyle zaten "
                        f"{MAX_AYNI_CAGRI} kez çağırdın; dosyalar değişmeden sonuç da "
                        "değişmez. Yaklaşımını değiştir: farklı bir şey dene veya "
                        "elindeki bilgiyle sonucu raporla.",
                    )
                # Rol kısıtı: bazı ajanlar (validator) mevcut dosyayı değiştiremez —
                # promptla değil mekanik olarak engellenir (write_file + edit_file)
                elif (
                    blok["name"] in ("write_file", "edit_file")
                    and ajan.mevcut_dosyayi_degistiremez
                    and self.executor.dosya_var_mi(girdi.get("path", ""))
                ):
                    sonuc = ToolSonucu(
                        False,
                        f"HATA: {ajan.ad} rolü var olan dosyayı değiştiremez "
                        f"({girdi.get('path')!r}). Düzeltme Debugger'ın işi; sen yalnızca "
                        "doğrula ve sonucu raporla.",
                    )
                elif (
                    blok["name"] == "run_shell"
                    and ajan.mevcut_dosyayi_degistiremez
                    and _YIKICI_KABUK.search(girdi.get("command", ""))
                ):
                    sonuc = ToolSonucu(
                        False,
                        f"HATA: {ajan.ad} rolü kabuk üzerinden dosya silemez, taşıyamaz "
                        "veya yönlendirmeyle (>) yazamaz. Yalnızca test/doğrulama "
                        "komutları çalıştır (örn. pytest, python <script>).",
                    )
                else:
                    sonuc = self.executor.calistir(blok["name"], girdi)
                    self.son_arac_sayisi += 1
                    if blok["name"] in ("write_file", "edit_file") and sonuc.ok:
                        # Durum değişti: bundan sonraki tekrarlar meşru
                        # (düzelt → yeniden test et döngüsü)
                        tekrar_sayaci.clear()
                        pespese_kabuk = 0
                        self.son_yazma_sayisi += 1
                    elif blok["name"] == "run_shell" or (
                        blok["name"] == "start_server" and not sonuc.ok
                    ):
                        # Başarısız start_server tekrarları da debelenmedir
                        # (canlıda validator port'suz çağrıyı ~12 kez kurcaladı)
                        pespese_kabuk += 1
                    else:
                        pespese_kabuk = 0

                    # Debelenme detektörü: dosya yazmadan çok sayıda kabuk komutu =
                    # ortam keşfi israfı (canlıda 12 tur 'echo hello' yakıldı)
                    if pespese_kabuk >= MAX_PESPESE_KABUK:
                        sonuc = ToolSonucu(
                            sonuc.ok,
                            sonuc.cikti
                            + f"\n[uyarı: {pespese_kabuk} kabuk komutunu üst üste dosya "
                            "yazmadan çalıştırdın. Ortamı keşfetmeyi bırak — komutlar "
                            "çalışıyor. Doğrudan gereken dosyaları write_file/edit_file "
                            "ile yaz ve göreve odaklan.]",
                        )

                # Şema uyarısı: bilinmeyen parametre sessizce yutulmasın, model
                # kendini düzeltebilsin (canlıda search_files'a 'path' verildi)
                bilinmeyen = set(girdi) - _ARAC_PARAMETRELERI.get(blok["name"], set(girdi))
                if bilinmeyen:
                    gecerli = ", ".join(sorted(_ARAC_PARAMETRELERI[blok["name"]]))
                    sonuc = ToolSonucu(
                        sonuc.ok,
                        sonuc.cikti
                        + f"\n[not: {', '.join(sorted(bilinmeyen))} diye parametre yok, "
                        f"yok sayıldı; geçerli parametreler: {gecerli}]",
                    )
                sonuc_bloklari.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": blok["id"],
                        "content": sonuc.cikti,
                        "is_error": not sonuc.ok,
                    }
                )
            mesajlar.append({"role": "user", "content": sonuc_bloklari})

        raise OrkestrasyonHatasi(
            f"{ajan.ad} ajanı {MAX_TOOL_TURU} tool turunda görevi bitiremedi "
            "(model büyük olasılıkla ilerleme kaydedemiyor; logdaki son araç "
            "çağrılarına bakın)"
        )

    # --- Aşamalar ---

    def _iptal_mi(self) -> None:
        """Kullanıcı iptal ettiyse IptalEdildi fırlatır (aksi halde no-op)."""
        if callable(self.iptal_kontrol) and self.iptal_kontrol():
            raise IptalEdildi("görev kullanıcı tarafından iptal edildi")

    def _asama(self, state: OturumState, ad: str, gorev_metni: str) -> str:
        """Aşamayı çalıştırır (daha önce bittiyse kayıtlı çıktıyı döndürür)."""
        if ad in state.tamamlanan:
            self._yaz(f"[{ad}] atlandı (önceki oturumda tamamlanmış)")
            return state.ciktilar[ad]
        self._iptal_mi()  # aşama başında iptal kontrolü
        self._yaz(f"[{ad}] başlıyor...")
        onceki = dict(getattr(self.istemci, "kullanim", None) or {})
        cikti = self.ajan_calistir(AJANLAR[ad], gorev_metni)
        state.asama_bitti(ad, cikti)
        state.kaydet(self.state_yolu)
        kullanim = getattr(self.istemci, "kullanim", None)
        if kullanim:
            girdi = kullanim["girdi"] - onceki.get("girdi", 0)
            cikis = kullanim["cikti"] - onceki.get("cikti", 0)
            self._yaz(f"[{ad}] bitti. ({girdi} giriş + {cikis} çıkış token)")
        else:
            self._yaz(f"[{ad}] bitti.")
        return cikti

    @staticmethod
    def _dogrulama_gecti(cikti: str) -> bool:
        """Validator çıktısının son işaret satırını yorumlar."""
        for satir in reversed(cikti.strip().splitlines()):
            satir = satir.strip()
            if BASARI_ISARETI in satir:
                return True
            if BASARISIZLIK_ISARETI in satir:
                return False
        raise OrkestrasyonHatasi(
            f"validator çıktısında '{BASARI_ISARETI}' / '{BASARISIZLIK_ISARETI}' "
            "işareti yok; çıktı:\n" + cikti[-500:]
        )

    def _kanitli_dogrulama(self, state: OturumState, metin: str) -> str:
        """Validator aşamasını koşar; kanıtsız kararı bir kez reddedip yeniden ister.

        Kanıt = o turda en az bir aracın gerçekten çalıştırılmış olması. Canlıda
        validator hiç araç çağırmadan (12k token düşünüp) hüküm verdi ve debugger
        var olmayan hatayı kovaladı; bu kural her iki yöndeki (BAŞARILI/BAŞARISIZ)
        kanıtsız kararı da keser.
        """
        onceden_tamam = "validator" in state.tamamlanan
        cikti = self._asama(state, "validator", metin)
        if onceden_tamam or self.son_arac_sayisi > 0:
            return cikti

        self._yaz(
            "[orkestratör] validator hiç araç çalıştırmadan karar verdi → "
            "reddedildi, kanıt isteniyor"
        )
        state.tamamlanan.remove("validator")
        cikti = self._asama(
            state,
            "validator",
            metin
            + "\n\nÖNEMLİ: Önceki cevabın reddedildi çünkü hiçbir araç çağırmadan "
            "karar verdin. Önce testleri/komutları GERÇEKTEN çalıştır, çıktılarını "
            "gör ve kararını bu kanıta dayandır.",
        )
        if self.son_arac_sayisi == 0:
            raise OrkestrasyonHatasi(
                "validator iki denemede de kanıt (araç çağrısı) olmadan karar verdi"
            )
        return cikti

    def dogrulamayi_coz(self, dogrulama: str) -> bool:
        """Doğrulama çıktısını yorumlar; işaret unutulmuşsa bir kez netleştirir.

        Modeller işaret satırını arada unutuyor (canlıda görüldü); işi baştan
        koşturmak yerine ucuz bir ek soruyla nihai sonucu isteriz.
        """
        try:
            return self._dogrulama_gecti(dogrulama)
        except OrkestrasyonHatasi:
            self._yaz("[orkestratör] validator işaret koymadı → netleştirme isteniyor")
            netlestirme = self.ajan_calistir(
                AJANLAR["validator"],
                "Az önce şu doğrulama çıktısını verdin:\n---\n"
                + dogrulama[-1500:]
                + "\n---\nBu doğrulamanın nihai sonucunu TEK satırla bildir: "
                f"'{BASARI_ISARETI}' ya da '{BASARISIZLIK_ISARETI}'. Başka bir şey yazma.",
            )
            return self._dogrulama_gecti(netlestirme)

    def _codegen_kos(self, state: OturumState, gorev: str, plan: str) -> None:
        """Codegen'i çalıştırır; hiç dosya yazmadıysa bir kez güçlü dürtüyle tekrarlar.

        Canlıda Nemotron ilk keşif turundan sonra kısa metin dönüp hiç write_file
        yapmadan durabiliyor (0 dosya üretti — 3 koşuda gözlendi). Sessizce ilerlemek,
        boş debug turları demek; bunun yerine 'planı UYGULA, dosyaları YAZ' diye bir
        kez daha ister. (Devam modunda önceden tamamlanmış codegen'e dokunmaz.)
        """
        onceden_tamam = "codegen" in state.tamamlanan
        self._asama(state, "codegen", f"Görev: {gorev}\n\nUygulanacak plan:\n{plan}")
        self._codegen_yazdi = self.son_yazma_sayisi > 0
        if onceden_tamam:
            return
        # İki dürtü koşulu:
        # (a) ARAÇ kullandı ama HİÇ dosya YAZMADI (list_files çağırıp metinle durdu)
        # (b) dosya yazdı ama ZORUNLU dosyalar eksik (ör. backend.py var, index.html yok)
        hic_yazmadi = self.son_yazma_sayisi == 0 and self.son_arac_sayisi > 0
        eksikler = self._eksik_zorunlu_dosyalar()
        if not hic_yazmadi and not eksikler:
            return
        if hic_yazmadi:
            uyari = (
                "ÖNEMLİ: Önceki denemende HİÇ dosya yazmadın — bu kabul edilemez. Planı "
                "AÇIKLAMA, UYGULA: write_file aracıyla gereken kod ve test dosyalarını "
                "(örn. backend.py, test_backend.py) ŞİMDİ oluştur. Metin yazma, dosya yaz."
            )
            self._yaz("[orkestratör] codegen hiç dosya yazmadı → dürtüyle tekrar isteniyor")
        else:
            uyari = (
                "ÖNEMLİ: Şu ZORUNLU dosyalar eksik: " + ", ".join(eksikler) + ". "
                "Bunları write_file ile ŞİMDİ oluştur; mevcut dosyaları koru. Metin yazma, dosya yaz."
            )
            self._yaz(f"[orkestratör] eksik dosya(lar): {', '.join(eksikler)} → codegen dürtülüyor")
        state.tamamlanan.remove("codegen")
        self._asama(
            state,
            "codegen",
            f"Görev: {gorev}\n\nUygulanacak plan:\n{plan}\n\n" + uyari,
        )
        self._codegen_yazdi = self._codegen_yazdi or self.son_yazma_sayisi > 0

    def _eksik_zorunlu_dosyalar(self) -> list[str]:
        """backend/fullstack için codegen sonrası eksik olan zorunlu dosyaları döndürür.

        backend: FastAPI modülü + en az bir test_*.py. fullstack: ayrıca index.html.
        Diğer tiplerde ([cpp]/None) zorunlu-dosya kontrolü yapılmaz (boş liste).
        """
        if self._dogrulama_tipi not in ("backend", "fullstack"):
            return []
        ws = self.executor.workspace
        eksik: list[str] = []
        if fastapi_uygulamasi_bul(ws) is None:
            eksik.append("backend.py (FastAPI uygulaması)")
        if not list(ws.glob("test_*.py")):
            eksik.append("test_backend.py")
        if self._dogrulama_tipi == "fullstack" and not (ws / "index.html").is_file():
            eksik.append("index.html")
        return eksik

    def _deterministik_dogrula(self) -> tuple[bool, str]:
        """Backend/full-stack tipinde doğrulamayı Runner ile deterministik yapar.

        Model hiç karışmaz. Backend: pytest (izole) + uvicorn + /openapi.json.
        Full-stack: ayrıca frontend'i açıp backend'e fetch bağlantısını AĞ düzeyinde
        kanıtlar. Sonuç ve gerekçe metni (debugger'a verilecek) döndürülür.
        """
        runner = FullstackRunner(self.executor.workspace, log=self._yaz)
        if self._dogrulama_tipi == "fullstack":
            rapor = runner.fullstack_dogrula()
        elif self._dogrulama_tipi == "cpp":
            rapor = runner.cpp_dogrula()
        else:
            rapor = runner.backend_dogrula()
        self._yaz(f"[runner] doğrulama: {'BAŞARILI' if rapor.gecti else 'BAŞARISIZ'}")
        return rapor.gecti, rapor.detay

    def _dogrula(self, state: OturumState, gorev: str, plan: str) -> tuple[bool, str]:
        """Doğrulamayı tipine göre yürütür; (geçti_mi, gerekçe_metni) döndürür.

        'backend'/'fullstack' tipinde deterministik Runner; aksi halde klasik
        model-doğrulama (kanıt şartı + işaret netleştirme).
        """
        if self._dogrulama_tipi in ("backend", "fullstack", "cpp"):
            return self._deterministik_dogrula()
        dogrulama = self._kanitli_dogrulama(
            state, f"Görev: {gorev}\n\nPlan:\n{plan}\n\nÜretilen işi doğrula."
        )
        return self.dogrulamayi_coz(dogrulama), dogrulama

    # --- Ana akış ---

    def gorev_calistir(self, gorev: str, devam: bool = False) -> OturumState:
        """Görevi uçtan uca yürütür; state'i döndürür.

        devam=True ise ve aynı görev için kayıtlı state varsa, tamamlanan
        aşamalar atlanarak kalınan yerden sürülür.
        """
        try:
            return self._gorev_calistir(gorev, devam)
        finally:
            # Hata da olsa açık arka plan sunucuları kapansın (sızıntı önleme)
            self.executor.temizle()

    def _gorev_calistir(self, gorev: str, devam: bool) -> OturumState:
        state = OturumState.yukle(self.state_yolu) if devam else None
        if state is None or state.gorev != gorev:
            state = OturumState(gorev=gorev)

        plan = self._asama(state, "planner", f"Görev: {gorev}\n\nBu görev için plan yap.")
        self._codegen_kos(state, gorev, plan)
        if self._takip and not self._codegen_yazdi:
            # Takipte sahte-başarı kapanı: eski proje zaten doğrulamadan geçer; codegen
            # hiçbir dosyayı değiştirmediyse "istek uygulandı" DENEMEZ. Net gerekçeyle
            # başarısız say → Debugger değişikliği kendisi uygular, sistem yeniden doğrular.
            self._yaz("[orkestratör] takip isteği uygulanmadı (hiç dosya değişmedi) → debugger")
            gecti, dogrulama = False, (
                "BAŞARISIZ: takip isteği UYGULANMADI — codegen hiçbir dosyayı "
                "değiştirmedi. Kullanıcının istediği değişiklik şu: " + gorev[:500] + "\n"
                "İlgili dosyaları oku ve isteği edit_file/write_file ile GERÇEKTEN uygula."
            )
        else:
            gecti, dogrulama = self._dogrula(state, gorev, plan)

        # Başarısızsa debugger ↔ doğrulama döngüsü (doğrulama: model ya da Runner)
        while not gecti:
            if state.debug_turu >= MAX_DEBUG_TURU:
                self._yaz(f"[orkestratör] {MAX_DEBUG_TURU} debug turu tükendi, bırakılıyor.")
                break
            state.debug_turu += 1
            self._yaz(f"[orkestratör] doğrulama başarısız → debugger (tur {state.debug_turu})")
            debug_cikti = self.ajan_calistir(
                AJANLAR["debugger"],
                f"Görev: {gorev}\n\nBaşarısız doğrulama çıktısı:\n{dogrulama}\n\n"
                "Sorunu bul ve düzelt. Hatada adı geçen dosyayı read_file ile AÇ, kök "
                "nedeni edit_file/write_file ile DÜZELT — sadece bakıp bırakma, MUTLAKA "
                "bir dosya değiştir.",
            )
            state.ciktilar[f"debugger_{state.debug_turu}"] = debug_cikti
            # No-op freni: debugger HİÇBİR dosyayı değiştirmediyse aynı testi tekrar
            # koşmak birebir aynı sonucu verir (canlıda 3 tur boşa harcandı) → erken bırak
            if self.son_yazma_sayisi == 0:
                self._yaz(
                    "[orkestratör] debugger düzeltme yapmadı (hiç dosya değişmedi) → bırakılıyor"
                )
                break
            # Doğrulamayı yeniden koş (önceki model-validator sonucunu geçersiz kıl;
            # Runner yolunda 'validator' zaten tamamlanan'da olmaz — no-op)
            if "validator" in state.tamamlanan:
                state.tamamlanan.remove("validator")
            gecti, dogrulama = self._dogrula(state, gorev, plan)

        state.ciktilar["dogrulama_gecti"] = str(gecti)
        # Reviewer yalnızca BAŞARILI koşuda koşar — başarısızda Runner'ın hata mesajı
        # zaten net; reviewer'ı çalıştırmak boşa token yakar (commit yine de yapılır).
        if gecti:
            self._asama(
                state,
                "reviewer",
                f"Görev: {gorev}\n\nÜretilen işi incele ve raporla.",
            )
        state.kaydet(self.state_yolu)

        # Workspace değişikliklerini tarihçeye yaz (izlenebilirlik + geri alma)
        if self.git:
            ozet = gorev.strip().splitlines()[0][:60]
            etiket = "basarili" if gecti else "basarisiz"
            if self.git.commit(f"orkestratör: {ozet} [{etiket}]"):
                self._yaz("[git] workspace değişiklikleri commit'lendi")
        return state
