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
        ("C++ ile uydu yörüngesi hesaplayan program yaz", "cpp"),
        ("std::cout kullanan bir hesap makinesi cpp dosyası", "cpp"),
        # C++ + web arayüzü açıkça istenirse full-stack kazanır (cpp değil)
        ("C++ hesabını gösteren full-stack FastAPI arayüzü ekle", "fullstack"),
    ],
)
def test_playbook_tespiti(gorev, beklenen):
    assert playbook_sec(gorev) == beklenen


# --- Enjeksiyon ---


def test_fullstack_tarifi_kritik_bilgiyi_icerir():
    """Kullanıcının artık yazmak zorunda olmadığı her şey tarifte olmalı.

    TEK-ORIGIN file-only akış: model sunucu/tarayıcı ÇALIŞTIRMAZ; backend index.html'i
    `/` kökünde servis eder, frontend GÖRELİ fetch kullanır — sabit port/CORS yok.
    """
    metin, ad = gorevi_zenginlestir("full-stack sayaç uygulaması istiyorum")
    assert ad == "fullstack"
    assert "FileResponse" in metin  # backend index.html'i servis eder (tek-origin)
    assert "GÖRELİ" in metin  # fetch('/todos') — sabit host/port yazılmaz
    assert "TestClient" in metin  # test yolu
    assert "fetch" in metin  # frontend backend'e BAĞLANMALI
    assert "DOM" in metin  # veriyi ekrana bas (entegrasyon)
    # Tek-origin: sabit portlar ve CORS tariften çıktı
    assert str(BACKEND_PORT) not in metin
    assert "CORSMiddleware" not in metin
    # Model sunucu/tarayıcı çalıştırmaz — bu araçlar tarifte olmamalı
    assert "start_server" not in metin
    assert "check_page" not in metin
    # De-prime: halüsinasyon tetikleyicisini adıyla anmıyoruz
    assert "docker" not in metin.lower()


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
