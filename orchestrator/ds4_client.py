"""DS4 (yerel DeepSeek V4 Flash) LLM istemcisi — ikinci, DENEYSEL sağlayıcı.

Nemotron'a dokunmadan eklenir. WSL2'de çalışan ds4-server'a (llama.cpp türevi)
Anthropic Messages formatında istek atar. ds4-server `/v1/messages`'ı NATİF konuşur
(tool_use dahil) → format çevirisi GEREKMEZ; sadece taban URL ds4-server'a çevrilir,
thinking kapatılır.

DS4 tek-kullanıcı ve çok yavaş (~0.5 tok/s): süreç genelinde tek-istek kilidi, çok
uzun zaman aşımı, thinking kapalı, küçük çıktı bütçesi. DS4 kapalıysa AÇIK hata —
sessiz Nemotron'a dönüş YOK (api.py'deki ön kontrol bunu erken yakalar).
"""

from __future__ import annotations

import os
import threading

import httpx

from orchestrator.llm_client import LLMIstemcisi

VARSAYILAN_DS4_URL = "http://localhost:8000"
# Okuma zaman aşımı YOK: DS4 bu donanımda çok yavaş (tek tur saatlerce sürebilir),
# üretim sınırsız beklesin. Yalnız BAĞLANTI için kısa sınır — sunucu kapalıysa
# saatlerce beklemek yerine hemen hata versin (api.py ön kontrolü de bunu yakalar).
DS4_ZAMAN_ASIMI = httpx.Timeout(None, connect=15.0)
# Küçük çıktı bütçesi süreyi sınırlar (istemci limit vermezse bu kullanılır)
DS4_VARSAYILAN_MAX_TOKENS = 1024

# DS4 aynı anda tek istek işler; süreç genelinde seri hale getir (çift emniyet —
# API zaten görev başına tek çalışır ama alt görev/ajan çağrıları bindirilmesin)
_DS4_KILIT = threading.Lock()


class DS4Istemcisi(LLMIstemcisi):
    """ds4-server'a bağlanan, thinking-kapalı, tek-istek seri LLM istemcisi."""

    def __init__(self, taban_url: str | None = None):
        taban = taban_url or os.environ.get("FCC_DS4_URL", VARSAYILAN_DS4_URL)
        super().__init__(taban_url=taban, zaman_asimi=DS4_ZAMAN_ASIMI)
        # ds4-server thinking'i istek gövdesinden kapatır (her isteğe eklenir)
        self.ek_govde = {"thinking": {"type": "disabled"}}
        # Bağlantı hatasında Nemotron değil DS4 ipucu göster
        self._baglanti_ipucu = (
            "ds4-server WSL'de çalışmıyor olabilir "
            "(./ds4-server --host 0.0.0.0 --port 8000)."
        )

    def mesaj_gonder(
        self,
        *,
        model: str,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        if max_tokens is None:
            max_tokens = int(
                os.environ.get("FCC_DS4_MAX_TOKENS", str(DS4_VARSAYILAN_MAX_TOKENS))
            )
        # DS4 tek istek işler → süreç genelinde seri
        with _DS4_KILIT:
            return super().mesaj_gonder(
                model=model,
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
            )
