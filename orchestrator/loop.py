"""Faz 2 — Orkestratör: agentic döngü.

Akış: Planner → Codegen → Test/Validator → (başarısızsa Debugger ↔ Validator,
en çok MAX_DEBUG_TURU tur) → Reviewer.

Her ajan kendi "tool döngüsünü" çalıştırır: model tool_use döndürdükçe araçlar
ToolExecutor ile yürütülür ve sonuçları tool_result olarak geri beslenir; model
metinle bitirince (end_turn) ajanın çıktısı alınır. Her aşamadan sonra state
diske yazılır (kesinti sonrası devam için).
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.agents import (
    AJANLAR,
    BASARI_ISARETI,
    BASARISIZLIK_ISARETI,
    AjanTanimi,
)
from orchestrator.llm_client import LLMIstemcisi
from orchestrator.state import OturumState
from orchestrator.tool_executor import TOOL_TANIMLARI, ToolExecutor

MAX_TOOL_TURU = 25  # bir ajanın tek görevde yapabileceği en fazla tool turu
MAX_DEBUG_TURU = 3  # doğrulama başarısız kaldıkça en fazla kaç debugger turu


class OrkestrasyonHatasi(RuntimeError):
    """Döngü ilerleyemedi (tool turu sınırı, işaretsiz doğrulama çıktısı vb.)."""


def _metin(yanit: dict) -> str:
    """Cevaptaki text bloklarını birleştirir."""
    return "\n".join(
        b.get("text", "") for b in yanit.get("content", []) if b.get("type") == "text"
    ).strip()


class Orkestrator:
    def __init__(
        self,
        workspace: Path | str,
        istemci: LLMIstemcisi | None = None,
        executor: ToolExecutor | None = None,
        state_yolu: Path | str = ".state/oturum.json",
        log: bool | object = True,
    ):
        self.executor = executor or ToolExecutor(workspace)
        self.istemci = istemci or LLMIstemcisi()
        self.state_yolu = Path(state_yolu)
        self._log = log

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

        for _ in range(MAX_TOOL_TURU):
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
                sonuc = self.executor.calistir(blok["name"], blok.get("input") or {})
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
            f"{ajan.ad} ajanı {MAX_TOOL_TURU} tool turunda görevi bitiremedi"
        )

    # --- Aşamalar ---

    def _asama(self, state: OturumState, ad: str, gorev_metni: str) -> str:
        """Aşamayı çalıştırır (daha önce bittiyse kayıtlı çıktıyı döndürür)."""
        if ad in state.tamamlanan:
            self._yaz(f"[{ad}] atlandı (önceki oturumda tamamlanmış)")
            return state.ciktilar[ad]
        self._yaz(f"[{ad}] başlıyor...")
        cikti = self.ajan_calistir(AJANLAR[ad], gorev_metni)
        state.asama_bitti(ad, cikti)
        state.kaydet(self.state_yolu)
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
        dogrulama = self._asama(
            state,
            "validator",
            f"Görev: {gorev}\n\nPlan:\n{plan}\n\nÜretilen işi doğrula.",
        )

        # Başarısızsa debugger ↔ validator döngüsü
        while not self._dogrulama_gecti(dogrulama):
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
            dogrulama = self._asama(
                state,
                "validator",
                f"Görev: {gorev}\n\nPlan:\n{plan}\n\nDüzeltme sonrası işi yeniden doğrula.",
            )

        state.ciktilar["dogrulama_gecti"] = str(self._dogrulama_gecti(dogrulama))
        self._asama(
            state,
            "reviewer",
            f"Görev: {gorev}\n\nÜretilen işi incele ve raporla.",
        )
        state.kaydet(self.state_yolu)
        return state
