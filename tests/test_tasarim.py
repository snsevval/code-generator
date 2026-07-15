"""Faz 7 — Tasarım bilgisi enjeksiyonu testleri (ağsız, sahte subprocess).

Çalıştırma:
    uv run pytest tests/test_tasarim.py -v
"""

from __future__ import annotations

from pathlib import Path

from orchestrator import tasarim


class SahteSonuc:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def test_gorev_zenginlestirilir(monkeypatch, tmp_path):
    script = tmp_path / "search.py"
    script.write_text("# sahte", encoding="utf-8")
    monkeypatch.setenv("FCC_TASARIM_SCRIPT", str(script))

    cagrilar = []

    def sahte_run(args, **kwargs):
        cagrilar.append(args)
        return SahteSonuc("## Design System\n- Primary: #7C3AED")

    monkeypatch.setattr(tasarim.subprocess, "run", sahte_run)

    sonuc = tasarim.gorevi_zenginlestir("portfolyo sayfası yap")
    assert "portfolyo sayfası yap" in sonuc
    assert "Uyulacak tasarım sistemi" in sonuc
    assert "#7C3AED" in sonuc
    # Script doğru bayraklarla çağrılmalı
    assert "--design-system" in cagrilar[0]
    assert any("portfolyo" in str(a) for a in cagrilar[0])


def test_script_yoksa_gorev_degismez(monkeypatch, tmp_path):
    monkeypatch.setenv("FCC_TASARIM_SCRIPT", str(tmp_path / "yok.py"))
    assert tasarim.gorevi_zenginlestir("görev") == "görev"


def test_script_hata_verirse_gorev_degismez(monkeypatch, tmp_path):
    script = tmp_path / "search.py"
    script.write_text("# sahte", encoding="utf-8")
    monkeypatch.setenv("FCC_TASARIM_SCRIPT", str(script))
    monkeypatch.setattr(tasarim.subprocess, "run", lambda *a, **k: SahteSonuc("", 1))
    assert tasarim.gorevi_zenginlestir("görev") == "görev"


def test_uzun_cikti_kirpilir(monkeypatch, tmp_path):
    script = tmp_path / "search.py"
    script.write_text("# sahte", encoding="utf-8")
    monkeypatch.setenv("FCC_TASARIM_SCRIPT", str(script))
    monkeypatch.setattr(
        tasarim.subprocess, "run", lambda *a, **k: SahteSonuc("X" * 10_000)
    )
    sonuc = tasarim.tasarim_sistemi("görev")
    assert len(sonuc) < 3000
    assert "kırpıldı" in sonuc


def test_gercek_skill_scripti_varsa_calisir(monkeypatch):
    """Makinede ui-ux-pro-max kuruluysa gerçek script koşulur (yavaşsa atla)."""
    monkeypatch.delenv("FCC_TASARIM_SCRIPT", raising=False)
    if not tasarim._script_yolu().is_file():
        import pytest

        pytest.skip("ui-ux-pro-max skill kurulu değil")
    sistem = tasarim.tasarim_sistemi("developer dashboard koyu tema")
    assert sistem is not None
    assert "Design System" in sistem or "Colors" in sistem or "Style" in sistem
