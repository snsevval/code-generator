"""Faz 0 — Tool-use tutarlılık testi.

free-claude-code proxy'sine (http://localhost:8082/v1/messages) Anthropic Messages API
formatında, tool tanımı içeren aynı isteği 10 kez gönderir ve her cevapta:

  a) type="tool_use" bloğu var mı,
  b) tool adı doğru mu ("read_file"),
  c) input geçerli mi ve zorunlu "path" alanını içeriyor mu

kontrollerini yapar. Sonunda özet rapor basar.

Çalıştırma:
    uv run python tests/test_tool_use_consistency.py   # ayrıntılı rapor
    uv run pytest tests/test_tool_use_consistency.py   # pytest ile (10/10 bekler)
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass

import httpx

# Windows konsolunda Türkçe karakterlerin bozulmaması için
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROXY_URL = "http://localhost:8082/v1/messages"
# Proxy'nin beklediği giriş anahtarı: ANTHROPIC_AUTH_TOKEN ortam değişkeninden okunur
# (proxy tarafındaki ~/.fcc/.env ile aynı değer olmalı; varsayılan: freecc)
AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN", "freecc")
# Model: "provider/model" biçimi proxy'de doğrudan o sağlayıcıya yönlenir
# (örn. "open_router/qwen/qwen3-coder:free"); Claude adı verilirse proxy'nin
# MODEL ayarındaki varsayılan rotaya gider.
TEST_MODEL = os.environ.get("FCC_TEST_MODEL", "claude-sonnet-4-20250514")
# Tekrar sayısı (hızlı sonda için FCC_TEST_REPEAT=1 verilebilir; varsayılan 10)
TEKRAR_SAYISI = int(os.environ.get("FCC_TEST_REPEAT", "10"))

# Hata tipleri (özet raporda gruplamak için)
HATA_TOOL_USE_YOK = "tool_use yok"
HATA_YANLIS_ISIM = "yanlış isim"
HATA_BOZUK_SEMA = "bozuk şema"
HATA_HTTP = "HTTP hatası"
HATA_SAGLAYICI = "sağlayıcı hatası (rate limit vb.)"

# Deneme başına yeniden deneme ve bekleme ayarları (rate limit'e takılmamak için)
DENEMELER_ARASI_BEKLEME_SN = float(os.environ.get("FCC_TEST_DELAY", "5"))
YENIDEN_DENEME_SAYISI = 3
YENIDEN_DENEME_BEKLEME_SN = 20.0

ISTEK_GOVDESI = {
    "model": TEST_MODEL,
    "max_tokens": 1024,
    "stream": False,
    "tools": [
        {
            "name": "read_file",
            "description": "Verilen yoldaki dosyanın içeriğini okur ve döndürür.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Okunacak dosyanın göreli yolu",
                    }
                },
                "required": ["path"],
            },
        }
    ],
    "messages": [
        {
            "role": "user",
            "content": "src/main.py dosyasını oku ve içeriğini özetle. "
            "Dosyayı okumak için mutlaka read_file aracını kullan.",
        }
    ],
}


@dataclass
class Sonuc:
    """Tek bir denemenin sonucu."""

    basarili: bool
    hata_tipi: str | None = None
    detay: str = ""


def cevabi_dogrula(cevap: dict) -> Sonuc:
    """Proxy cevabındaki tool_use bloğunu üç kritere göre doğrular."""
    icerik = cevap.get("content") or []
    tool_use_bloklari = [b for b in icerik if b.get("type") == "tool_use"]

    # a) tool_use bloğu var mı?
    if not tool_use_bloklari:
        metin = " ".join(b.get("text", "") for b in icerik if b.get("type") == "text")
        # Proxy, üst sağlayıcı hatalarını (rate limit vb.) 200 + metin olarak
        # döndürebiliyor; bunlar model davranışı değil, altyapı hatasıdır
        if metin.startswith(("Upstream provider", "Provider request failed")):
            return Sonuc(False, HATA_SAGLAYICI, metin.splitlines()[0][:120])
        return Sonuc(False, HATA_TOOL_USE_YOK, f"model tool çağırmadı, metin döndü: {metin[:120]!r}")

    blok = tool_use_bloklari[0]

    # b) tool adı doğru mu?
    if blok.get("name") != "read_file":
        return Sonuc(False, HATA_YANLIS_ISIM, f"beklenen 'read_file', gelen: {blok.get('name')!r}")

    # c) input geçerli JSON mu ve zorunlu "path" alanını içeriyor mu?
    girdi = blok.get("input")
    if isinstance(girdi, str):
        # Bazı sağlayıcılar input'u string döndürebiliyor; JSON olarak çözmeyi dene
        try:
            girdi = json.loads(girdi)
        except json.JSONDecodeError:
            return Sonuc(False, HATA_BOZUK_SEMA, f"input geçerli JSON değil: {girdi[:120]!r}")
    if not isinstance(girdi, dict):
        return Sonuc(False, HATA_BOZUK_SEMA, f"input sözlük değil: {type(girdi).__name__}")
    if not isinstance(girdi.get("path"), str) or not girdi["path"].strip():
        return Sonuc(False, HATA_BOZUK_SEMA, f"zorunlu 'path' alanı eksik/geçersiz: {girdi!r}")

    return Sonuc(True, detay=f"path={girdi['path']!r}")


def tek_istek(istemci: httpx.Client) -> Sonuc:
    """Tek bir isteği gönderir ve sonucunu döndürür."""
    try:
        yanit = istemci.post(
            PROXY_URL,
            json=ISTEK_GOVDESI,
            headers={
                "x-api-key": AUTH_TOKEN,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
    except httpx.ConnectError:
        print(
            f"[HATA] {PROXY_URL} adresine bağlanılamadı — proxy çalışmıyor olabilir.\n"
            "       Ayrı bir terminalde fcc-server'ı başlatıp tekrar deneyin.",
            file=sys.stderr,
        )
        sys.exit(1)

    if yanit.status_code == 429:
        return Sonuc(False, HATA_SAGLAYICI, f"HTTP 429: {yanit.text[:120]}")
    if yanit.status_code != 200:
        return Sonuc(False, HATA_HTTP, f"HTTP {yanit.status_code}: {yanit.text[:200]}")
    return cevabi_dogrula(yanit.json())


def denemeleri_calistir(tekrar: int = TEKRAR_SAYISI) -> list[Sonuc]:
    """İsteği `tekrar` kez gönderir; sağlayıcı hatalarında bekleyip yeniden dener."""
    sonuclar: list[Sonuc] = []
    with httpx.Client(timeout=120.0) as istemci:
        for i in range(1, tekrar + 1):
            if i > 1 and DENEMELER_ARASI_BEKLEME_SN > 0:
                time.sleep(DENEMELER_ARASI_BEKLEME_SN)

            sonuc = tek_istek(istemci)
            # Rate limit / geçici sağlayıcı hataları model davranışını ölçmez;
            # bekleyip yeniden dene
            yeniden = 0
            while sonuc.hata_tipi == HATA_SAGLAYICI and yeniden < YENIDEN_DENEME_SAYISI:
                yeniden += 1
                print(
                    f"  Deneme {i:2d}: sağlayıcı hatası, {YENIDEN_DENEME_BEKLEME_SN:.0f} sn "
                    f"bekleyip yeniden denenecek ({yeniden}/{YENIDEN_DENEME_SAYISI}) — {sonuc.detay}"
                )
                time.sleep(YENIDEN_DENEME_BEKLEME_SN)
                sonuc = tek_istek(istemci)

            durum = "BAŞARILI" if sonuc.basarili else f"BAŞARISIZ ({sonuc.hata_tipi})"
            print(f"  Deneme {i:2d}/{tekrar}: {durum} — {sonuc.detay}")
            sonuclar.append(sonuc)
    return sonuclar


def rapor_bas(sonuclar: list[Sonuc]) -> int:
    """Özet raporu basar, başarılı deneme sayısını döndürür."""
    basarili = sum(1 for s in sonuclar if s.basarili)
    print("\n" + "=" * 60)
    print(f"ÖZET: {basarili}/{len(sonuclar)} deneme geçerli tool_use üretti")
    hatalar = Counter(s.hata_tipi for s in sonuclar if not s.basarili)
    if hatalar:
        print("Başarısızlık dağılımı:")
        for tip, adet in hatalar.most_common():
            print(f"  - {tip}: {adet}")
    else:
        print("Tüm denemeler başarılı — tool-use tutarlılığı doğrulandı.")
    print("=" * 60)
    return basarili


def _proxy_ayakta() -> bool:
    try:
        httpx.get(PROXY_URL.replace("/v1/messages", "/health"), timeout=5.0)
        return True
    except httpx.TransportError:
        return False


def test_tool_use_tutarliligi():
    """pytest girişi: 10 denemenin tamamı geçerli tool_use üretmeli."""
    import pytest

    if not _proxy_ayakta():
        pytest.skip("proxy (fcc-server) çalışmıyor — entegrasyon testi atlandı")
    sonuclar = denemeleri_calistir()
    basarili = rapor_bas(sonuclar)
    assert basarili == len(sonuclar), (
        f"tool-use tutarlılığı yetersiz: {basarili}/{len(sonuclar)} "
        "(hata dağılımı için yukarıdaki rapora bakın)"
    )


if __name__ == "__main__":
    print(f"Tool-use tutarlılık testi başlıyor ({TEKRAR_SAYISI} deneme, hedef: {PROXY_URL})")
    print(f"Model: {TEST_MODEL}\n")
    n = rapor_bas(denemeleri_calistir())
    sys.exit(0 if n == TEKRAR_SAYISI else 2)
