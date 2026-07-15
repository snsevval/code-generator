"""Faz 5 — Git entegrasyonu ve token sayacı testleri.

Çalıştırma:
    uv run pytest tests/test_git_ve_token.py -v
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from orchestrator.agents import BASARI_ISARETI
from orchestrator.git_deposu import GitDeposu
from orchestrator.llm_client import LLMIstemcisi
from orchestrator.loop import Orkestrator

from tests.test_orchestrator import FakeIstemci, metin_cevap, validator_cevaplari

git_gerekli = pytest.mark.skipif(shutil.which("git") is None, reason="git kurulu değil")


def _log(ws, *args) -> str:
    # git çıktısı UTF-8'dir; Windows yerel kod sayfasına bırakılırsa Türkçe bozulur
    return subprocess.run(
        ["git", "-C", str(ws), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


# --- GitDeposu ---


@git_gerekli
def test_olustur_repo_kurar_ve_commit_atar(tmp_path):
    depo = GitDeposu.olustur(tmp_path)
    assert depo is not None
    (tmp_path / "a.txt").write_text("merhaba", encoding="utf-8")

    assert depo.commit("ilk değişiklik") is True
    assert "ilk değişiklik" in _log(tmp_path, "log", "--oneline")


@git_gerekli
def test_degisiklik_yoksa_commit_atmaz(tmp_path):
    depo = GitDeposu.olustur(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert depo.commit("bir") is True
    assert depo.commit("iki") is False  # değişiklik yok
    assert "iki" not in _log(tmp_path, "log", "--oneline")


@git_gerekli
def test_ust_repo_icinde_kendi_reposunu_kurar(tmp_path):
    """Görev klasörü bir üst reponun içindeyse commit'ler ÜST repoya gitmemeli.

    Canlıda yaşandı: workspace ana projenin içinde olduğundan orkestratör,
    commit'lenmemiş proje kodunu ana repoya kendi mesajıyla commit'ledi.
    """
    subprocess.run(["git", "-C", str(tmp_path), "init"], capture_output=True)
    (tmp_path / "ana_dosya.py").write_text("x = 1", encoding="utf-8")
    ic = tmp_path / "workspace" / "gorev-1"
    ic.mkdir(parents=True)

    depo = GitDeposu.olustur(ic)
    assert depo is not None
    assert (ic / ".git").is_dir()  # kendi reposu kuruldu

    (ic / "uretilen.py").write_text("y = 2", encoding="utf-8")
    assert depo.commit("görev bitti") is True

    # Üst reponun tarihçesi ve indeksi el değmemiş kalmalı
    ust_log = _log(tmp_path, "log", "--oneline")
    assert "görev bitti" not in ust_log
    ust_durum = subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain"],
        capture_output=True, text=True, encoding="utf-8",
    ).stdout
    assert "ana_dosya.py" in ust_durum  # hâlâ commit'lenmemiş (bizim dokunmadığımız) halde


def test_fcc_git_kapatir(tmp_path, monkeypatch):
    monkeypatch.setenv("FCC_GIT", "0")
    assert GitDeposu.olustur(tmp_path) is None


@git_gerekli
def test_gorev_sonunda_otomatik_commit(tmp_path):
    senaryo = (
        [metin_cevap("plan"), metin_cevap("kod")]
        + validator_cevaplari(BASARI_ISARETI)
        + [metin_cevap("rapor")]
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    ork = Orkestrator(
        ws,
        istemci=FakeIstemci(senaryo),
        state_yolu=tmp_path / "s.json",
        log=False,
        git=GitDeposu.olustur(ws),
    )
    (ws / "uretilen.py").write_text("print(1)", encoding="utf-8")

    ork.gorev_calistir("küçük bir araç yaz")

    gecmis = _log(ws, "log", "--oneline")
    assert "orkestratör: küçük bir araç yaz [basarili]" in gecmis


# --- Token sayacı ---


class SahteHttpYaniti:
    status_code = 200

    def json(self):
        return {
            "content": [{"type": "text", "text": "tamam"}],
            "usage": {"input_tokens": 100, "output_tokens": 40},
        }


def test_llm_istemcisi_kullanim_biriktirir(monkeypatch):
    istemci = LLMIstemcisi(taban_url="http://localhost:9")
    monkeypatch.setattr(istemci._istemci, "post", lambda *a, **k: SahteHttpYaniti())

    istemci.mesaj_gonder(model="m", messages=[{"role": "user", "content": "selam"}])
    istemci.mesaj_gonder(model="m", messages=[{"role": "user", "content": "tekrar"}])

    assert istemci.kullanim == {"istek": 2, "girdi": 200, "cikti": 80}


def test_asama_loglari_token_deltasi_icerir(tmp_path):
    class SayaclıFake(FakeIstemci):
        def __init__(self, senaryo):
            super().__init__(senaryo)
            self.kullanim = {"istek": 0, "girdi": 0, "cikti": 0}

        def mesaj_gonder(self, **kwargs):
            self.kullanim["istek"] += 1
            self.kullanim["girdi"] += 50
            self.kullanim["cikti"] += 10
            return super().mesaj_gonder(**kwargs)

    senaryo = (
        [metin_cevap("plan"), metin_cevap("kod")]
        + validator_cevaplari(BASARI_ISARETI)
        + [metin_cevap("rapor")]
    )
    loglar: list[str] = []
    ws = tmp_path / "ws"
    ws.mkdir()
    ork = Orkestrator(
        ws,
        istemci=SayaclıFake(senaryo),
        state_yolu=tmp_path / "s.json",
        log=loglar.append,
        git=False,
    )
    ork.gorev_calistir("görev")

    assert any("50 giriş + 10 çıkış token" in satir for satir in loglar)