"""Faz 4 — Proje orkestratörü: büyük hedefleri alt görev zincirine böler.

Akış:
  1. Decomposer ajanı hedefi JSON alt görev listesine çevirir
  2. Her alt görev, mevcut tek-görev döngüsüyle (Planner→...→Reviewer) koşulur
  3. Biten alt görevin özeti + güncel dosya listesi sonraki görevin bağlamına eklenir
  4. Bir alt görev doğrulamadan geçemezse zincir durur (sonrakiler ona bağımlı)

Proje durumu `.state/proje.json`'a yazılır; `devam=True` ile başarılı alt
görevler atlanarak kalınan yerden sürülür.
"""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.agents import AJANLAR
from orchestrator.loop import Orkestrator, OrkestrasyonHatasi
from orchestrator.state import ProjeState

OZET_SINIRI = 500  # alt görev özetinin sonraki bağlama taşınan azami uzunluğu


def _json_dizisi_ayikla(metin: str) -> list[dict]:
    """Model cevabındaki JSON dizisini ayıklar (``` çitleri ve önsöz toleranslı)."""
    bas, son = metin.find("["), metin.rfind("]")
    if bas == -1 or son <= bas:
        raise OrkestrasyonHatasi(
            "decomposer çıktısında JSON dizisi bulunamadı:\n" + metin[:300]
        )
    try:
        veri = json.loads(metin[bas : son + 1])
    except json.JSONDecodeError as e:
        raise OrkestrasyonHatasi(f"decomposer JSON'ı çözülemedi: {e}") from e
    if not isinstance(veri, list) or not veri:
        raise OrkestrasyonHatasi("decomposer boş/geçersiz alt görev listesi döndürdü")
    for oge in veri:
        if not isinstance(oge, dict) or not str(oge.get("gorev", "")).strip():
            raise OrkestrasyonHatasi(f"geçersiz alt görev öğesi: {oge!r}")
    return veri


class ProjeOrkestratoru:
    def __init__(
        self,
        workspace: Path | str,
        orkestrator: Orkestrator | None = None,
        state_klasoru: Path | str = ".state",
        log: bool | object = True,
        onay_callback=None,
    ):
        self.state_klasoru = Path(state_klasoru)
        self.ork = orkestrator or Orkestrator(workspace, log=log)
        self._log = log
        # Verilirse her başarılı alt görevden sonra çağrılır (alt görev dict'iyle);
        # False dönerse zincir durdurulur (UI'deki insan onay noktası)
        self._onay = onay_callback

    def _yaz(self, mesaj: str) -> None:
        if callable(self._log):
            self._log(mesaj)
        elif self._log:
            print(mesaj, flush=True)

    @property
    def proje_state_yolu(self) -> Path:
        return self.state_klasoru / "proje.json"

    # --- Aşama 1: hedefi böl ---

    def hedefi_bol(self, hedef: str) -> ProjeState:
        self._yaz("[decomposer] hedef alt görevlere bölünüyor...")
        cikti = self.ork.ajan_calistir(
            AJANLAR["decomposer"], f"Hedef: {hedef}\n\nBu hedefi alt görevlere böl."
        )
        alt_gorevler = [
            {
                "id": int(oge.get("id", i + 1)),
                "gorev": str(oge["gorev"]).strip(),
                "kabul": str(oge.get("kabul", "")).strip(),
                "durum": "bekliyor",
                "ozet": "",
            }
            for i, oge in enumerate(_json_dizisi_ayikla(cikti))
        ]
        self._yaz(f"[decomposer] {len(alt_gorevler)} alt görev çıkarıldı.")
        return ProjeState(hedef=hedef, alt_gorevler=alt_gorevler)

    # --- Aşama 2: zinciri koş ---

    def _alt_gorev_metni(self, state: ProjeState, alt: dict) -> str:
        onceki = "\n".join(
            f"- [{o['id']}] {o['gorev']}: {o['ozet'] or o['durum']}"
            for o in state.alt_gorevler
            if o["durum"] == "basarili"
        )
        dosyalar = self.ork.executor.list_files().cikti
        parcalar = [
            f"Proje hedefi: {state.hedef}",
            f"Bu alt görev: {alt['gorev']}",
        ]
        if alt["kabul"]:
            parcalar.append(f"Kabul ölçütü: {alt['kabul']}")
        if onceki:
            parcalar.append(f"Tamamlanan önceki alt görevler:\n{onceki}")
        parcalar.append(f"Workspace'teki mevcut dosyalar:\n{dosyalar}")
        return "\n\n".join(parcalar)

    def hedef_calistir(self, hedef: str, devam: bool = False) -> ProjeState:
        state = ProjeState.yukle(self.proje_state_yolu) if devam else None
        if state is None or state.hedef != hedef:
            state = self.hedefi_bol(hedef)
            state.kaydet(self.proje_state_yolu)

        for alt in state.alt_gorevler:
            if alt["durum"] == "basarili":
                self._yaz(f"[proje] alt görev {alt['id']} atlandı (tamamlanmış)")
                continue

            self._yaz(f"[proje] alt görev {alt['id']}/{len(state.alt_gorevler)}: {alt['gorev']}")
            # Görev metni bir kez üretilip state'e yazılır: metin, o anki dosya
            # listesini içerdiğinden her üretimde değişir; sabitlemezsek iç-döngü
            # devam mekanizması görevi tanıyamaz ve baştan başlar
            if not alt.get("gorev_metni"):
                alt["gorev_metni"] = self._alt_gorev_metni(state, alt)
                state.kaydet(self.proje_state_yolu)
            # Her alt görevin kendi iç-döngü state'i olur (kesintide iç devam için)
            self.ork.state_yolu = self.state_klasoru / f"alt_{alt['id']}.json"
            try:
                oturum = self.ork.gorev_calistir(alt["gorev_metni"], devam=devam)
            except OrkestrasyonHatasi as e:
                # Tek alt görevin tıkanması (örn. tool turu sınırı) zinciri sert
                # düşürmesin: görevi başarısız işaretle ve düzgünce dur
                self._yaz(f"[proje] alt görev {alt['id']} tıkandı: {e}")
                alt["durum"] = "basarisiz"
                alt["ozet"] = f"tıkandı: {e}"[:OZET_SINIRI]
                state.kaydet(self.proje_state_yolu)
                break

            gecti = oturum.ciktilar.get("dogrulama_gecti") == "True"
            alt["durum"] = "basarili" if gecti else "basarisiz"
            # Codegen'in kendi özeti sonraki görevlerin bağlamına taşınır
            alt["ozet"] = oturum.ciktilar.get("codegen", "")[:OZET_SINIRI]
            state.kaydet(self.proje_state_yolu)

            if not gecti:
                self._yaz(
                    f"[proje] alt görev {alt['id']} doğrulamadan geçemedi — zincir durdu "
                    "(sonraki görevler buna bağımlı olabilir)."
                )
                break

            # İnsan onay noktası: kalan görev varsa ve callback tanımlıysa sor
            kalan_var = any(a["durum"] == "bekliyor" for a in state.alt_gorevler)
            if self._onay is not None and kalan_var:
                self._yaz(f"[proje] alt görev {alt['id']} tamamlandı — onay bekleniyor...")
                if not self._onay(alt):
                    self._yaz("[proje] kullanıcı zinciri durdurdu.")
                    break

        self._entegrasyonu_dogrula(state)
        return state

    def _entegrasyonu_dogrula(self, state: ProjeState) -> None:
        """Tüm alt görevler bittiyse parçaların birlikte çalıştığını sınar."""
        if state.entegrasyon == "basarili":
            self._yaz("[proje] entegrasyon doğrulaması atlandı (önceden geçmiş)")
            return
        if not all(a["durum"] == "basarili" for a in state.alt_gorevler):
            return  # zincir tamamlanmadı; entegrasyona geçilmez

        self._yaz("[proje] final entegrasyon doğrulaması başlıyor...")
        liste = "\n".join(f"- [{a['id']}] {a['gorev']}" for a in state.alt_gorevler)
        istek = (
            f"Proje hedefi: {state.hedef}\n\nTamamlanan alt görevler:\n{liste}\n\n"
            "Parçaların BİRLİKTE çalıştığını uçtan uca doğrula: tüm testleri koş "
            "(pytest) ve ana kullanım akışını gerçekten dene. Tek tek modüller değil, "
            "bütün önemli."
        )
        cikti = self.ork.ajan_calistir(AJANLAR["validator"], istek)
        # Kanıt şartı: entegrasyon kararı da araç çalıştırmadan verilemez
        if getattr(self.ork, "son_arac_sayisi", 1) == 0:
            self._yaz("[proje] entegrasyon kararı kanıtsız → yeniden isteniyor")
            cikti = self.ork.ajan_calistir(
                AJANLAR["validator"],
                istek
                + "\n\nÖNEMLİ: Önceki cevabın reddedildi çünkü hiçbir araç çağırmadan "
                "karar verdin. Testleri GERÇEKTEN çalıştırıp kanıta dayan.",
            )
        gecti = self.ork.dogrulamayi_coz(cikti)
        state.entegrasyon = "basarili" if gecti else "basarisiz"
        state.kaydet(self.proje_state_yolu)
        self._yaz(f"[proje] entegrasyon doğrulaması: {state.entegrasyon.upper()}")
