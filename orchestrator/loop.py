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
from orchestrator.git_deposu import GitDeposu
from orchestrator.llm_client import LLMIstemcisi
from orchestrator.state import OturumState
from orchestrator.tool_executor import TOOL_TANIMLARI, ToolExecutor, ToolSonucu

MAX_TOOL_TURU = 25  # bir ajanın tek görevde yapabileceği en fazla tool turu
MAX_DEBUG_TURU = 3  # doğrulama başarısız kaldıkça en fazla kaç debugger turu
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

# Şema uyarısı için: araç adı → geçerli parametre adları
_ARAC_PARAMETRELERI = {
    t["name"]: set(t["input_schema"].get("properties", {})) for t in TOOL_TANIMLARI
}


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
    ):
        self.executor = executor or ToolExecutor(workspace)
        self.istemci = istemci or LLMIstemcisi()
        self.state_yolu = Path(state_yolu)
        self._log = log
        # Son ajan_calistir çağrısında gerçekten yürütülen araç sayısı
        # (kanıt şartı: doğrulama kararları araçsız kabul edilmez)
        self.son_arac_sayisi = 0
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
        araclar = [t for t in TOOL_TANIMLARI if t["name"] in ajan.araclar]
        mesajlar: list[dict] = [{"role": "user", "content": gorev_metni}]
        self.son_arac_sayisi = 0
        tekrar_sayaci: dict[tuple, int] = {}

        for _ in range(MAX_TOOL_TURU):
            _gecmisi_kirp(mesajlar)
            yanit = self.istemci.mesaj_gonder(
                model=ajan.model,
                system=ajan.sistem_prompt,
                tools=araclar or None,
                messages=mesajlar,
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
                # promptla değil mekanik olarak engellenir
                elif (
                    blok["name"] == "write_file"
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
                    if blok["name"] == "write_file" and sonuc.ok:
                        # Durum değişti: bundan sonraki tekrarlar meşru
                        # (düzelt → yeniden test et döngüsü)
                        tekrar_sayaci.clear()

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

    def _asama(self, state: OturumState, ad: str, gorev_metni: str) -> str:
        """Aşamayı çalıştırır (daha önce bittiyse kayıtlı çıktıyı döndürür)."""
        if ad in state.tamamlanan:
            self._yaz(f"[{ad}] atlandı (önceki oturumda tamamlanmış)")
            return state.ciktilar[ad]
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

    # --- Ana akış ---

    def gorev_calistir(self, gorev: str, devam: bool = False) -> OturumState:
        """Görevi uçtan uca yürütür; state'i döndürür.

        devam=True ise ve aynı görev için kayıtlı state varsa, tamamlanan
        aşamalar atlanarak kalınan yerden sürülür.
        """
        state = OturumState.yukle(self.state_yolu) if devam else None
        if state is None or state.gorev != gorev:
            state = OturumState(gorev=gorev)

        plan = self._asama(state, "planner", f"Görev: {gorev}\n\nBu görev için plan yap.")
        self._asama(
            state, "codegen", f"Görev: {gorev}\n\nUygulanacak plan:\n{plan}"
        )
        dogrulama = self._kanitli_dogrulama(
            state, f"Görev: {gorev}\n\nPlan:\n{plan}\n\nÜretilen işi doğrula."
        )

        # Başarısızsa debugger ↔ validator döngüsü
        gecti = self.dogrulamayi_coz(dogrulama)
        while not gecti:
            if state.debug_turu >= MAX_DEBUG_TURU:
                self._yaz(f"[orkestratör] {MAX_DEBUG_TURU} debug turu tükendi, bırakılıyor.")
                break
            state.debug_turu += 1
            self._yaz(f"[orkestratör] doğrulama başarısız → debugger (tur {state.debug_turu})")
            debug_cikti = self.ajan_calistir(
                AJANLAR["debugger"],
                f"Görev: {gorev}\n\nBaşarısız doğrulama çıktısı:\n{dogrulama}\n\n"
                "Sorunu bul ve düzelt.",
            )
            state.ciktilar[f"debugger_{state.debug_turu}"] = debug_cikti
            # Doğrulamayı yeniden koş (önceki sonucu geçersiz kıl)
            if "validator" in state.tamamlanan:
                state.tamamlanan.remove("validator")
            dogrulama = self._kanitli_dogrulama(
                state,
                f"Görev: {gorev}\n\nPlan:\n{plan}\n\nDüzeltme sonrası işi yeniden doğrula.",
            )
            gecti = self.dogrulamayi_coz(dogrulama)

        state.ciktilar["dogrulama_gecti"] = str(gecti)
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
