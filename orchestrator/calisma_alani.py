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

# Görev klasörüne konan izolasyon dosyaları — önleyici sigorta. Workspace ana
# projenin İÇİNDE olduğundan, ajan dosya belirtmeden `pytest` çalıştırırsa pytest
# rootdir'i yukarı tırmanıp ana projenin pyproject.toml'unu (testpaths=["tests"])
# bulur ve ana projenin testlerini (test_docker_sandbox vb.) toplamaya çalışır.
# Kendi pytest.ini + conftest.py rootdir'i görev klasörüne kilitler ve klasörü
# import yoluna ekler. (git_deposu'nun kendi-repo düzeltmesiyle aynı kök neden:
# workspace ana projenin içinde.)
_PYTEST_INI = "[pytest]\npythonpath = .\n"
_CONFTEST = (
    "# Görev klasörünü rootdir sabitler (ana projenin pytest ayarları sızmasın).\n"
    "import sys\nfrom pathlib import Path\n"
    "sys.path.insert(0, str(Path(__file__).parent))\n"
)


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
    # pytest'i bu klasöre hapset (ana projenin config'i sızmasın)
    (klasor / "pytest.ini").write_text(_PYTEST_INI, encoding="utf-8")
    (klasor / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    return klasor
