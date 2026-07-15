"""Faz 5 — Görev başına izole çalışma klasörü.

Her yeni görev, workspace kökü altında kendi temiz klasöründe koşar
(gorev-YYYYAAGG-SSDDss / proje-...). Böylece önceki görevlerin dosyaları
yeni görevin planına/testlerine sızmaz (canlıda yaşandı: eski projenin
testleri yeni görevin doğrulamasını kirletti).

Son kullanılan klasör kök içindeki bir işaret dosyasına yazılır; `devam=True`
aynı klasörü bulup sürdürür. "Mevcut projenin üzerinde çalış" senaryosu da
bu yolla (devam) veya klasörü doğrudan vererek çalışır.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

KAYIT_DOSYASI = ".son_gorev_klasoru"


def gorev_klasoru_sec(taban: Path | str, devam: bool = False, proje: bool = False) -> Path:
    """Görev için çalışma klasörünü döndürür (gerekirse oluşturur)."""
    taban = Path(taban).resolve()
    taban.mkdir(parents=True, exist_ok=True)
    kayit = taban / KAYIT_DOSYASI

    if devam and kayit.is_file():
        aday = taban / kayit.read_text(encoding="utf-8").strip()
        if aday.is_dir():
            return aday
        # Kayıtlı klasör silinmiş; yeni klasörle devam etmek en güvenlisi

    ad = ("proje-" if proje else "gorev-") + datetime.now().strftime("%Y%m%d-%H%M%S")
    klasor = taban / ad
    sayac = 1
    while klasor.exists():  # aynı saniyede ikinci görev
        sayac += 1
        klasor = taban / f"{ad}-{sayac}"
    klasor.mkdir()
    kayit.write_text(klasor.name, encoding="utf-8")
    return klasor
