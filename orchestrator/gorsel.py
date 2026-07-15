"""Faz 7 — Görsel analiz: ekran görüntüsünü Gemini'ye gösterir.

Ajanlar hangi modelde koşarsa koşsun (Nemotron görüntü anlamıyor), screenshot
doğrudan Gemini REST'e gönderilir ve kısa bir Türkçe UI değerlendirmesi METİN
olarak geri döner; check_page bu metni araç çıktısına ekler. Böylece proxy'nin
görüntü desteğine bağımlılık yoktur (karma model kararı).

Anahtar/ağ yoksa None döner — check_page yapısal sonuçla devam eder.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import httpx

VARSAYILAN_SORU = (
    "Bu bir web sayfasının ekran görüntüsü. Görsel kalite sorunlarını değerlendir: "
    "taşma, hizasızlık, okunmayan kontrast, üst üste binen öğeler, bozuk düzen var mı? "
    "En fazla 5 madde, kısa ve Türkçe. Sorun yoksa 'Görsel sorun yok' de."
)


def _gemini_anahtari() -> str | None:
    """GEMINI_API_KEY ortam değişkeni; yoksa proxy'nin ~/.fcc/.env dosyasından."""
    anahtar = os.environ.get("GEMINI_API_KEY", "").strip()
    if anahtar:
        return anahtar
    dosya = Path.home() / ".fcc" / ".env"
    if dosya.is_file():
        eslesme = re.search(
            r"^GEMINI_API_KEY=(.+)$", dosya.read_text(encoding="utf-8"), re.MULTILINE
        )
        if eslesme:
            return eslesme.group(1).strip().strip('"') or None
    return None


def gorsel_acik() -> bool:
    """Görsel analiz etkin mi? FCC_GORSEL=0 kapatır; varsayılan: anahtar varsa açık."""
    ayar = os.environ.get("FCC_GORSEL", "").lower()
    if ayar in ("0", "false", "no"):
        return False
    return _gemini_anahtari() is not None


def gorsel_analiz(png_yolu: Path | str, soru: str = VARSAYILAN_SORU) -> str | None:
    """Ekran görüntüsünü Gemini'yle analiz eder; kısa rapor döner (hatada None)."""
    anahtar = _gemini_anahtari()
    if not anahtar:
        return None
    png_yolu = Path(png_yolu)
    if not png_yolu.is_file():
        return None

    model = os.environ.get("FCC_GORSEL_MODEL", "gemini-2.5-flash")
    try:
        yanit = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": anahtar},
            json={
                "contents": [
                    {
                        "parts": [
                            {
                                "inline_data": {
                                    "mime_type": "image/png",
                                    "data": base64.b64encode(png_yolu.read_bytes()).decode(),
                                }
                            },
                            {"text": soru},
                        ]
                    }
                ]
            },
            timeout=60.0,
        )
        yanit.raise_for_status()
        parcalar = yanit.json()["candidates"][0]["content"]["parts"]
        metin = "\n".join(p.get("text", "") for p in parcalar).strip()
        return metin or None
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None  # görsel analiz opsiyonel: hata, aracı düşürmesin
