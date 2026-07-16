"""Faz 9 — Playbook katmanı testleri (deterministik, kotasız).

Çalıştırma:
    uv run pytest tests/test_playbook.py -v
"""

from __future__ import annotations

import pytest

from orchestrator.playbook import (
    BACKEND_PORT,
    FRONTEND_PORT,
    gorevi_zenginlestir,
    playbook_sec,
)


# --- Tespit ---


@pytest.mark.parametrize(
    "gorev, beklenen",
    [
        ("arayüz tasarımı olan full-stack sayaç uygulaması istiyorum", "fullstack"),
        ("Backend FastAPI, frontend HTML olan bir yapılacaklar uygulaması", "fullstack"),
        ("FastAPI ile ürün listeleyen bir API yaz", "backend"),
        ("kişisel portfolyo sayfası yap, şık görünsün", "frontend"),
        ("Vite + React ile sayaç uygulaması", "vite"),
        ("npm kullanan gerçek React projesi kur", "vite"),
        ("fibonacci hesaplayan CLI aracı yaz, pytest ile", None),  # playbook'suz
        ("csv dosyasını okuyup ortalama hesaplayan script", None),
    ],
)
def test_playbook_tespiti(gorev, beklenen):
    assert playbook_sec(gorev) == beklenen


# --- Enjeksiyon ---


def test_fullstack_tarifi_kritik_bilgiyi_icerir():
    """Kullanıcının artık yazmak zorunda olmadığı her şey tarifte olmalı."""
    metin, ad = gorevi_zenginlestir("full-stack sayaç uygulaması istiyorum")
    assert ad == "fullstack"
    assert str(BACKEND_PORT) in metin  # port konvansiyonu
    assert str(FRONTEND_PORT) in metin
    assert "start_server" in metin  # doğru araç
    assert '"port"' in metin  # örnekli çağrı (port debelenmesine karşı)
    assert "stop_server" in metin  # temizlik
    assert "check_page" in metin  # canlı doğrulama
    assert "CORSMiddleware" in metin  # iki katman konuşabilsin
    assert "TestClient" in metin  # test yolu


def test_vite_tarifi_bilinen_tuzaklari_kapatir():
    metin, ad = gorevi_zenginlestir("Vite ile react projesi kur")
    assert ad == "vite"
    assert "vite.config.js" in metin  # canlıda unutulan dosya
    assert "file://" in metin  # file:// doğrulama tuzağı
    assert "npm install" in metin


def test_playbooksuz_gorev_degismez():
    gorev = "fibonacci hesaplayan CLI aracı yaz"
    metin, ad = gorevi_zenginlestir(gorev)
    assert ad is None
    assert metin == gorev


def test_kullanici_kisa_yazar_sistem_detay_ekler():
    """Faz 9'un varlık sebebi: 60 karakterlik istek, tarifle zenginleşir."""
    kisa = "şık arayüzlü full-stack not uygulaması, backend FastAPI"
    metin, _ = gorevi_zenginlestir(kisa)
    assert len(metin) > len(kisa) * 5  # sistem detayı sistem ekledi
    assert metin.startswith(kisa)  # kullanıcının isteği aynen korunur
