"""Aşama 1 — Deterministik Full-stack Runner testleri (model/proxy gerekmez).

Runner gerçek bir FastAPI backend'ini pytest + uvicorn ile deterministik doğrular;
bu testler o davranışı gerçek dosyalarla uçtan uca doğrular.

Çalıştırma:
    uv run pytest tests/test_fullstack_runner.py -v
"""

from __future__ import annotations

import pytest

from orchestrator.calisma_alani import gorev_klasoru_sec
from orchestrator.fullstack_runner import (
    FullstackRunner,
    bos_port_bul,
    cpp_kaynagi_bul,
    fastapi_uygulamasi_bul,
    gpp_bul,
)

# uvicorn/fastapi yoksa sunucu-başlatan testler anlamsız
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")


BACKEND_OK = (
    "from fastapi import FastAPI\n"
    "app = FastAPI()\n"
    "_items = []\n"
    "@app.post('/reset')\n"
    "def reset():\n"
    "    _items.clear()\n"
    "    return {'ok': True}\n"
    "@app.post('/items')\n"
    "def ekle(x: dict):\n"
    "    _items.append(x)\n"
    "    return x\n"
    "@app.get('/items')\n"
    "def items():\n"
    "    return _items\n"
)

TEST_OK = (
    "from fastapi.testclient import TestClient\n"
    "from backend import app\n"
    "c = TestClient(app)\n"
    "def test_bos_baslar():\n"
    "    c.post('/reset')\n"
    "    assert c.get('/items').json() == []\n"
    "def test_ekleme():\n"
    "    c.post('/reset')\n"
    "    c.post('/items', json={'ad': 'x'})\n"
    "    assert len(c.get('/items').json()) == 1\n"
)


def _ws(tmp_path):
    """İzole görev klasörü (pytest.ini/conftest dahil)."""
    return gorev_klasoru_sec(tmp_path)


# --- Uygulama tespiti ---


def test_fastapi_uygulamasi_bul(tmp_path):
    ws = _ws(tmp_path)
    (ws / "backend.py").write_text(BACKEND_OK, encoding="utf-8")
    assert fastapi_uygulamasi_bul(ws) == ("backend", "app")


def test_fastapi_uygulamasi_yoksa_none(tmp_path):
    ws = _ws(tmp_path)
    (ws / "yardim.py").write_text("x = 1\n", encoding="utf-8")
    assert fastapi_uygulamasi_bul(ws) is None


def test_fastapi_farkli_degisken_adi(tmp_path):
    ws = _ws(tmp_path)
    (ws / "main.py").write_text("from fastapi import FastAPI\nuygulama = FastAPI()\n", encoding="utf-8")
    assert fastapi_uygulamasi_bul(ws) == ("main", "uygulama")


def test_bos_port_bul_farkli_ve_pozitif():
    p1, p2 = bos_port_bul(), bos_port_bul()
    assert p1 > 0 and p2 > 0


# --- backend_dogrula: başarısızlık yolları (hızlı) ---


def test_kod_yoksa_basarisiz(tmp_path):
    # Sadece sistem dosyaları var (pytest.ini/conftest) → sahte BASARILI OLMAMALI
    ws = _ws(tmp_path)
    rapor = FullstackRunner(ws).backend_dogrula()
    assert rapor.gecti is False
    assert "bulunamadı" in rapor.detay


def test_test_yoksa_basarisiz(tmp_path):
    ws = _ws(tmp_path)
    (ws / "backend.py").write_text(BACKEND_OK, encoding="utf-8")
    rapor = FullstackRunner(ws).backend_dogrula()
    assert rapor.gecti is False
    assert "test" in rapor.detay.lower()


def test_pytest_patlarsa_basarisiz(tmp_path):
    ws = _ws(tmp_path)
    (ws / "backend.py").write_text(BACKEND_OK, encoding="utf-8")
    (ws / "test_backend.py").write_text(
        "from backend import app  # noqa\ndef test_patlar():\n    assert 1 == 2\n",
        encoding="utf-8",
    )
    rapor = FullstackRunner(ws).backend_dogrula()
    assert rapor.gecti is False
    assert "pytest" in rapor.detay.lower()


# --- backend_dogrula: mutlu yol (gerçek uvicorn başlatır) ---


def test_mutlu_yol_pytest_ve_sunucu(tmp_path):
    ws = _ws(tmp_path)
    (ws / "backend.py").write_text(BACKEND_OK, encoding="utf-8")
    (ws / "test_backend.py").write_text(TEST_OK, encoding="utf-8")
    rapor = FullstackRunner(ws).backend_dogrula()
    assert rapor.gecti is True, rapor.detay
    assert "serve ediyor" in rapor.detay


# --- Full-stack entegrasyon (backend + frontend + tarayıcı ağ kontrolü) ---


def _tarayici_hazir() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


_TARAYICI = _tarayici_hazir()

# TEK-ORIGIN: backend hem /items'i hem index.html'i `/` kökünde servis eder (dinamik port).
BACKEND_ITEMS = (
    "from fastapi import FastAPI\n"
    "from fastapi.responses import FileResponse\n"
    "app = FastAPI()\n"
    "_items = [{'id': 1, 'title': 'RUNNER'}]\n"
    "@app.get('/items')\n"
    "def items():\n"
    "    return _items\n"
    "@app.get('/')\n"
    "def index():\n"
    "    return FileResponse('index.html')\n"
)
# Bağlı: sayfa yüklenince GÖRELİ fetch atıp DOM'a basar (aynı origin)
FRONTEND_BAGLI = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'><title>T</title></head><body>"
    "<ul id='l'></ul><script>"
    "fetch('/items').then(r=>r.json())"
    ".then(d=>{document.getElementById('l').textContent=JSON.stringify(d);})"
    ".catch(e=>console.error(e));"
    "</script></body></html>"
)
# Bağımsız: backend'e HİÇ istek atmayan sayfa (örn. sadece yerel sayaç)
FRONTEND_BAGIMSIZ = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'><title>S</title></head><body>"
    "<h1 id='c'>0</h1><script>let n=0;</script></body></html>"
)


@pytest.mark.skipif(not _TARAYICI, reason="playwright chromium yok")
def test_fullstack_bagli_frontend_gecer(tmp_path):
    ws = _ws(tmp_path)
    (ws / "backend.py").write_text(BACKEND_ITEMS, encoding="utf-8")
    (ws / "index.html").write_text(FRONTEND_BAGLI, encoding="utf-8")
    rapor = FullstackRunner(ws).fullstack_dogrula()
    assert rapor.gecti is True, rapor.detay
    assert "veri çekti" in rapor.detay


# Buton-tetiklemeli: açılışta fetch YOK; "Hesapla" butonuna basılınca fetch atar
# (canlıda yörünge uygulaması bu desende yanlış 'bağlantısız' sayılmıştı)
FRONTEND_BUTONLU = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'><title>B</title></head><body>"
    "<button id='hesapla'>Hesapla</button><div id='sonuc'></div><script>"
    "document.getElementById('hesapla').addEventListener('click', function(){"
    "fetch('/items').then(r=>r.json())"
    ".then(d=>{document.getElementById('sonuc').textContent=JSON.stringify(d);})"
    ".catch(e=>console.error(e));});"
    "</script></body></html>"
)


@pytest.mark.skipif(not _TARAYICI, reason="playwright chromium yok")
def test_fullstack_buton_tetiklemeli_fetch_gecer(tmp_path):
    # Açılışta istek atmayan ama butonla atan sayfa: Runner butona tıklayıp doğrulamalı
    ws = _ws(tmp_path)
    (ws / "backend.py").write_text(BACKEND_ITEMS, encoding="utf-8")
    (ws / "index.html").write_text(FRONTEND_BUTONLU, encoding="utf-8")
    rapor = FullstackRunner(ws).fullstack_dogrula()
    assert rapor.gecti is True, rapor.detay


@pytest.mark.skipif(not _TARAYICI, reason="playwright chromium yok")
def test_fullstack_kopuk_frontend_basarisiz(tmp_path):
    ws = _ws(tmp_path)
    (ws / "backend.py").write_text(BACKEND_ITEMS, encoding="utf-8")
    (ws / "index.html").write_text(FRONTEND_BAGIMSIZ, encoding="utf-8")
    rapor = FullstackRunner(ws).fullstack_dogrula()
    assert rapor.gecti is False
    assert "istek atmadı" in rapor.detay or "bağlı değil" in rapor.detay


def test_fullstack_frontend_yoksa_basarisiz(tmp_path):
    ws = _ws(tmp_path)
    (ws / "backend.py").write_text(BACKEND_ITEMS, encoding="utf-8")
    rapor = FullstackRunner(ws).fullstack_dogrula()
    assert rapor.gecti is False
    assert "index.html" in rapor.detay or "frontend" in rapor.detay.lower()


# --- C++ doğrulama (g++ ile derle + çalıştır) ---

_GPP = gpp_bul()

CPP_OK = (
    "#include <iostream>\n"
    "int main() {\n"
    "    double a, b;\n"
    "    std::cin >> a >> b;\n"
    "    std::cout << (a + b) << std::endl;\n"
    "    return 0;\n"
    "}\n"
)
# Derleme hatası: tanımsız değişken (canlıda 'TodoModel'/'const' tipi hataları gibi)
CPP_DERLEME_HATASI = (
    "#include <iostream>\n"
    "int main() {\n"
    "    std::cout << tanimsiz_degisken << std::endl;\n"
    "    return 0;\n"
    "}\n"
)


def test_cpp_kaynak_bulma_alt_klasor(tmp_path):
    ws = _ws(tmp_path)
    (ws / "src").mkdir()
    (ws / "src" / "main.cpp").write_text(CPP_OK, encoding="utf-8")
    bulunan = cpp_kaynagi_bul(ws)
    assert bulunan is not None and bulunan.name == "main.cpp"


def test_cpp_kaynak_yoksa_none(tmp_path):
    ws = _ws(tmp_path)
    assert cpp_kaynagi_bul(ws) is None


def test_cpp_kaynak_yoksa_basarisiz(tmp_path):
    ws = _ws(tmp_path)
    rapor = FullstackRunner(ws).cpp_dogrula()
    assert rapor.gecti is False
    assert ".cpp" in rapor.detay


@pytest.mark.skipif(not _GPP, reason="g++ derleyicisi yok")
def test_cpp_dogru_kod_derlenir_ve_calisir(tmp_path):
    ws = _ws(tmp_path)
    (ws / "main.cpp").write_text(CPP_OK, encoding="utf-8")
    rapor = FullstackRunner(ws).cpp_dogrula()
    assert rapor.gecti is True, rapor.detay
    assert (ws / "program.exe").is_file()


@pytest.mark.skipif(not _GPP, reason="g++ derleyicisi yok")
def test_cpp_derleme_hatasi_basarisiz(tmp_path):
    ws = _ws(tmp_path)
    (ws / "main.cpp").write_text(CPP_DERLEME_HATASI, encoding="utf-8")
    rapor = FullstackRunner(ws).cpp_dogrula()
    assert rapor.gecti is False
    assert "derleme" in rapor.detay.lower()
