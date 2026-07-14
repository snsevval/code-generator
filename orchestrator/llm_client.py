"""Faz 2 — LLM istemcisi.

free-claude-code proxy'sine Anthropic Messages API biçiminde istek atar.
Geçici hatalarda (429, 5xx, proxy'nin metne gömdüğü sağlayıcı hataları)
bekleyip yeniden dener; kalıcı hatalarda ProxyHatasi fırlatır.
"""

from __future__ import annotations

import os
import time

import httpx

VARSAYILAN_PROXY_URL = "http://localhost:8082"
# Ücretsiz katmanlarda dakikalık kotalar dar (örn. Gemini free ~10 istek/dk);
# bekleme süreleri bir dakikalık pencereyi aşacak şekilde artar: 20s, 40s, 60s
YENIDEN_DENEME_SAYISI = 4
YENIDEN_DENEME_BEKLEME_SN = 20.0


class ProxyHatasi(RuntimeError):
    """Proxy'ye ulaşılamadı veya kalıcı hata döndü."""


def _saglayici_hata_metni(yanit: dict) -> str | None:
    """Proxy'nin 200 + metin olarak sardığı üst sağlayıcı hatasını yakalar."""
    icerik = yanit.get("content") or []
    metinler = [b.get("text", "") for b in icerik if b.get("type") == "text"]
    if len(icerik) == len(metinler) and metinler:
        birlesik = "\n".join(metinler)
        if birlesik.startswith(("Upstream provider", "Provider request failed")):
            # Teşhis için hatanın tamamını (makul sınırda) koru
            return " | ".join(birlesik.splitlines())[:400]
    return None


class LLMIstemcisi:
    """Proxy'ye tek tip erişim; ajanlar bunu paylaşır."""

    def __init__(
        self,
        taban_url: str | None = None,
        auth_token: str | None = None,
        zaman_asimi: float = 300.0,
    ):
        taban = (taban_url or os.environ.get("FCC_PROXY_URL", VARSAYILAN_PROXY_URL)).rstrip("/")
        self._url = f"{taban}/v1/messages"
        self._auth = auth_token or os.environ.get("ANTHROPIC_AUTH_TOKEN", "freecc")
        self._istemci = httpx.Client(timeout=zaman_asimi)
        # Token sayacı: kota takibi için oturum boyunca birikir
        self.kullanim = {"istek": 0, "girdi": 0, "cikti": 0}

    def mesaj_gonder(
        self,
        *,
        model: str,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Bir Messages isteği gönderir, ham cevap sözlüğünü döndürür."""
        if max_tokens is None:
            # Bazı sağlayıcılar (örn. Groq) max_tokens'ı isteğin token bütçesine
            # peşinen sayar; gereksiz büyük değer günlük kotayı hızla eritir
            max_tokens = int(os.environ.get("FCC_MAX_TOKENS", "4096"))
        govde: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": False,
            "messages": messages,
        }
        if system:
            govde["system"] = system
        if tools:
            govde["tools"] = tools

        son_hata = ""
        for deneme in range(1, YENIDEN_DENEME_SAYISI + 1):
            try:
                yanit = self._istemci.post(
                    self._url,
                    json=govde,
                    headers={
                        "x-api-key": self._auth,
                        "anthropic-version": "2023-06-01",
                    },
                )
            except httpx.ConnectError as e:
                raise ProxyHatasi(
                    f"{self._url} adresine bağlanılamadı — proxy çalışmıyor olabilir, "
                    "fcc-server'ı başlatın."
                ) from e

            if yanit.status_code in (429, 500, 502, 503, 529):
                son_hata = f"HTTP {yanit.status_code}"
            elif yanit.status_code != 200:
                raise ProxyHatasi(f"HTTP {yanit.status_code}: {yanit.text[:300]}")
            else:
                veri = yanit.json()
                saglayici_hatasi = _saglayici_hata_metni(veri)
                if saglayici_hatasi is None:
                    k = veri.get("usage") or {}
                    self.kullanim["istek"] += 1
                    self.kullanim["girdi"] += int(k.get("input_tokens") or 0)
                    self.kullanim["cikti"] += int(k.get("output_tokens") or 0)
                    return veri
                son_hata = saglayici_hatasi

            if deneme < YENIDEN_DENEME_SAYISI:
                time.sleep(YENIDEN_DENEME_BEKLEME_SN * deneme)

        raise ProxyHatasi(f"yeniden denemeler tükendi, son hata: {son_hata}")

    def kapat(self) -> None:
        self._istemci.close()
