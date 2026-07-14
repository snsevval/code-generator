"""Faz 3 — Repo indeksi testleri (varsayılan arka uç ağsızdır).

Çalıştırma:
    uv run pytest tests/test_indeks.py -v
"""

from __future__ import annotations

import pytest

from orchestrator.indeks import (
    GeminiVektorleyici,
    RepoIndeksi,
    TfIdfVektorleyici,
    _parcala,
)
from orchestrator.tool_executor import ToolExecutor


# --- Parçalayıcı ---


def test_parcala_camel_ve_snake_case():
    parcalar = _parcala("def kullaniciAdiGetir(user_name): pass")
    assert "kullaniciadigetir" in parcalar  # tam tanımlayıcı
    assert "kullanici" in parcalar and "getir" in parcalar  # camelCase parçaları
    assert "user" in parcalar and "name" in parcalar  # snake_case parçaları


# --- TF-IDF arama ---


@pytest.fixture
def dolu_workspace(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def login(password, username):\n    '''Kullanıcı girişi doğrular'''\n", encoding="utf-8"
    )
    (tmp_path / "db.py").write_text(
        "class DatabaseConnection:\n    def baglan(self): ...\n", encoding="utf-8"
    )
    (tmp_path / "utils.py").write_text("def topla(a, b): return a + b\n", encoding="utf-8")
    return tmp_path


def test_sorgula_ilgili_dosyayi_bulur(dolu_workspace):
    sonuclar = RepoIndeksi(dolu_workspace).sorgula("kullanıcı login password doğrulama")
    assert sonuclar, "sonuç boş olmamalı"
    assert sonuclar[0]["dosya"] == "auth.py"
    assert sonuclar[0]["skor"] > 0


def test_sorgula_ornek_satir_icerir(dolu_workspace):
    sonuclar = RepoIndeksi(dolu_workspace).sorgula("database connection")
    assert sonuclar[0]["dosya"] == "db.py"
    assert "DatabaseConnection" in sonuclar[0]["ornek"]


def test_gizli_klasorler_indekslenmez(tmp_path):
    (tmp_path / "gercek.py").write_text("elma armut", encoding="utf-8")
    gizli = tmp_path / "__pycache__"
    gizli.mkdir()
    (gizli / "kopya.py").write_text("elma armut", encoding="utf-8")

    sonuclar = RepoIndeksi(tmp_path).sorgula("elma")
    dosyalar = [s["dosya"] for s in sonuclar]
    assert "gercek.py" in dosyalar
    assert all("__pycache__" not in d for d in dosyalar)


def test_bos_workspace(tmp_path):
    assert RepoIndeksi(tmp_path).sorgula("bir şey") == []
    assert RepoIndeksi(tmp_path).sorgula_metin("bir şey") == "Eşleşen dosya bulunamadı."


def test_metin_disi_uzantilar_atlanir(tmp_path):
    (tmp_path / "veri.bin").write_bytes(b"\x00\x01elma")
    (tmp_path / "kod.py").write_text("elma", encoding="utf-8")
    dosyalar = [s["dosya"] for s in RepoIndeksi(tmp_path).sorgula("elma")]
    assert dosyalar == ["kod.py"]


# --- search_files aracı ---


def test_search_files_araci(dolu_workspace):
    executor = ToolExecutor(dolu_workspace)
    sonuc = executor.calistir("search_files", {"query": "login password"})
    assert sonuc.ok
    assert "auth.py" in sonuc.cikti
    assert "skor" in sonuc.cikti


def test_search_files_bos_sorgu(dolu_workspace):
    sonuc = ToolExecutor(dolu_workspace).calistir("search_files", {})
    assert not sonuc.ok


# --- Gemini arka ucu (sahte HTTP ile) ---


def test_gemini_vektorleyici_kosinus(monkeypatch):
    """Gemini arka ucu: API çağrıları sahtelenir, kosinüs sıralaması doğrulanır."""

    class SahteYanit:
        def __init__(self, vektorler):
            self._v = vektorler

        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": [{"values": v} for v in self._v]}

    cagrilar = []

    def sahte_post(url, headers=None, json=None, timeout=None):
        cagrilar.append(json)
        adet = len(json["requests"])
        if adet == 2:  # belgeler: biri sorguyla aynı yönde, biri dik
            return SahteYanit([[1.0, 0.0], [0.0, 1.0]])
        return SahteYanit([[1.0, 0.0]])  # sorgu

    monkeypatch.setattr("orchestrator.indeks.httpx.post", sahte_post)

    v = GeminiVektorleyici(api_key="test-anahtar")
    skorlar = v.vektorle(["ilgili belge", "alakasız belge"], "sorgu")
    assert skorlar[0] > 0.99 and skorlar[1] < 0.01
    # Belge ve sorgu için ayrı taskType kullanılmalı
    assert cagrilar[0]["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert cagrilar[1]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_gemini_anahtarsiz_hata(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiVektorleyici()


def test_varsayilan_arka_uc_tfidf(monkeypatch):
    monkeypatch.delenv("FCC_EMBEDDING", raising=False)
    assert isinstance(RepoIndeksi(".")._vektorleyici, TfIdfVektorleyici)
