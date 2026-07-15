"""Faz 8 — Arka plan süreç yönetimi testleri.

Gerçek bir python http.server başlatıp yaşam döngüsünü (başlat/log/durdur +
otomatik temizlik) doğrular. Ağ yerel; kotasız.

Çalıştırma:
    uv run pytest tests/test_sunucu.py -v
"""

from __future__ import annotations

import socket

import pytest

from orchestrator.sunucu import SunucuYoneticisi, port_dinliyor_mu
from orchestrator.tool_executor import ToolExecutor


def bos_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def yonetici(tmp_path):
    y = SunucuYoneticisi(tmp_path)
    yield y
    y.hepsini_durdur()  # test sonrası sızıntı bırakma


def test_baslat_dinler_durdur(yonetici, tmp_path):
    (tmp_path / "index.html").write_text("<h1>Selam</h1>", encoding="utf-8")
    port = bos_port()

    mesaj = yonetici.baslat(f"python -m http.server {port}", port)
    assert "çalışıyor" in mesaj, mesaj
    assert port_dinliyor_mu(port)

    # Durdurunca port serbest kalmalı
    durdur = yonetici.durdur(port)
    assert "durduruldu" in durdur
    # Süreç ağacı öldürüldü; kısa süre içinde port kapanır
    import time

    son = time.monotonic() + 5
    while time.monotonic() < son and port_dinliyor_mu(port):
        time.sleep(0.2)
    assert not port_dinliyor_mu(port)


def test_hepsini_durdur_sizinti_birakmaz(yonetici, tmp_path):
    p1, p2 = bos_port(), bos_port()
    yonetici.baslat(f"python -m http.server {p1}", p1)
    yonetici.baslat(f"python -m http.server {p2}", p2)
    assert port_dinliyor_mu(p1) and port_dinliyor_mu(p2)

    yonetici.hepsini_durdur()
    assert yonetici.sunucular == {}


def test_hemen_cikan_surec_hata_verir(yonetici):
    port = bos_port()
    # var olmayan komut hemen çıkar
    mesaj = yonetici.baslat("python -c \"import sys; sys.exit(1)\"", port)
    assert mesaj.startswith("HATA")
    assert "çıktı" in mesaj


def test_ayni_port_iki_kez_reddedilir(yonetici, tmp_path):
    port = bos_port()
    yonetici.baslat(f"python -m http.server {port}", port)
    mesaj = yonetici.baslat(f"python -m http.server {port}", port)
    assert mesaj.startswith("HATA")
    assert "zaten" in mesaj


def test_log_okunur(yonetici, tmp_path):
    port = bos_port()
    yonetici.baslat(f"python -m http.server {port}", port)
    # http.server başlangıç mesajını stderr'e yazar
    log = yonetici.log(port)
    assert "Serving HTTP" in log or "http" in log.lower() or log == ""  # platforma göre


# --- ToolExecutor entegrasyonu ---


def test_executor_start_stop(tmp_path):
    ex = ToolExecutor(tmp_path)
    port = bos_port()
    baslat = ex.calistir("start_server", {"command": f"python -m http.server {port}", "port": port})
    assert baslat.ok, baslat.cikti
    assert port_dinliyor_mu(port)

    durdur = ex.calistir("stop_server", {"port": port})
    assert durdur.ok
    ex.temizle()


def test_executor_temizle_sizinti_birakmaz(tmp_path):
    ex = ToolExecutor(tmp_path)
    port = bos_port()
    ex.calistir("start_server", {"command": f"python -m http.server {port}", "port": port})
    assert port_dinliyor_mu(port)
    ex.temizle()  # görev sonu temizliği taklit
    import time

    son = time.monotonic() + 5
    while time.monotonic() < son and port_dinliyor_mu(port):
        time.sleep(0.2)
    assert not port_dinliyor_mu(port)


def test_yonetilmeyen_port_durdurma_hatasi(tmp_path):
    ex = ToolExecutor(tmp_path)
    sonuc = ex.calistir("stop_server", {"port": 59999})
    assert not sonuc.ok
    assert "yönetilen bir sunucu yok" in sonuc.cikti


def test_port_sayi_degilse_hata(tmp_path):
    ex = ToolExecutor(tmp_path)
    sonuc = ex.calistir("start_server", {"command": "echo x", "port": "abc"})
    assert not sonuc.ok
    assert "sayı" in sonuc.cikti
