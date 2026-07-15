"""Faz 5 — Görev başına izole klasör testleri.

Çalıştırma:
    uv run pytest tests/test_calisma_alani.py -v
"""

from __future__ import annotations

from orchestrator.calisma_alani import KAYIT_DOSYASI, gorev_klasoru_sec


def test_yeni_gorevler_farkli_klasor_alir(tmp_path):
    k1 = gorev_klasoru_sec(tmp_path)
    k2 = gorev_klasoru_sec(tmp_path)
    assert k1 != k2
    assert k1.is_dir() and k2.is_dir()
    assert k1.name.startswith("gorev-") and k2.name.startswith("gorev-")


def test_devam_son_klasoru_kullanir(tmp_path):
    k1 = gorev_klasoru_sec(tmp_path)
    (k1 / "yarim_is.py").write_text("x", encoding="utf-8")

    k2 = gorev_klasoru_sec(tmp_path, devam=True)
    assert k2 == k1
    assert (k2 / "yarim_is.py").exists()


def test_proje_oneki(tmp_path):
    k = gorev_klasoru_sec(tmp_path, proje=True)
    assert k.name.startswith("proje-")


def test_kayit_dosyasi_guncellenir(tmp_path):
    k1 = gorev_klasoru_sec(tmp_path)
    assert (tmp_path / KAYIT_DOSYASI).read_text(encoding="utf-8") == k1.name
    k2 = gorev_klasoru_sec(tmp_path)
    assert (tmp_path / KAYIT_DOSYASI).read_text(encoding="utf-8") == k2.name


def test_kayitli_klasor_silinmisse_yeni_acilir(tmp_path):
    k1 = gorev_klasoru_sec(tmp_path)
    (k1 / "iz.txt").write_text("x", encoding="utf-8")
    import shutil

    shutil.rmtree(k1)
    k2 = gorev_klasoru_sec(tmp_path, devam=True)
    # Yeni (boş) bir klasör açılmalı; adı aynı olabilir ama içerik sıfırdan
    assert k2.is_dir()
    assert list(k2.iterdir()) == []


def test_izolasyon_eski_dosyalar_gorunmez(tmp_path):
    k1 = gorev_klasoru_sec(tmp_path)
    (k1 / "eski_test.py").write_text("assert False", encoding="utf-8")
    k2 = gorev_klasoru_sec(tmp_path)
    assert not (k2 / "eski_test.py").exists()
    assert list(k2.iterdir()) == []
