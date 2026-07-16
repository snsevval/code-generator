"""Faz 7 — check_page (göz) ve görsel analiz testleri.

Playwright/Chromium kurulu değilse tarayıcı testleri atlanır.

Çalıştırma:
    uv run pytest tests/test_check_page.py -v
"""

from __future__ import annotations

import pytest

from orchestrator import gorsel
from orchestrator.tool_executor import ToolExecutor


def _playwright_hazir() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


tarayici_gerekli = pytest.mark.skipif(
    not _playwright_hazir(), reason="playwright/chromium kurulu değil"
)


@pytest.fixture(autouse=True)
def gorsel_kapali(monkeypatch):
    """Birim testlerde gerçek Gemini'ye gidilmesin."""
    monkeypatch.setenv("FCC_GORSEL", "0")


@tarayici_gerekli
def test_temiz_sayfa(tmp_path):
    (tmp_path / "sayfa.html").write_text(
        "<!doctype html><html><head><title>Deneme</title></head>"
        "<body><h1>Merhaba</h1></body></html>",
        encoding="utf-8",
    )
    sonuc = ToolExecutor(tmp_path).check_page("sayfa.html")
    assert sonuc.ok, sonuc.cikti
    assert "Deneme" in sonuc.cikti
    assert "Konsol: temiz" in sonuc.cikti
    assert (tmp_path / ".kontrol" / "sayfa.png").is_file()  # screenshot alındı


@tarayici_gerekli
def test_konsol_hatasi_yakalanir(tmp_path):
    (tmp_path / "bozuk.html").write_text(
        "<!doctype html><html><body><script>"
        "console.error('kritik hata'); tanimsizFonksiyon();"
        "</script></body></html>",
        encoding="utf-8",
    )
    sonuc = ToolExecutor(tmp_path).check_page("bozuk.html")
    assert sonuc.ok  # sayfa açıldı; hatalar rapora girer, araç düşmez
    assert "kritik hata" in sonuc.cikti
    assert "pageerror" in sonuc.cikti  # tanımsız fonksiyon yakalandı


def test_workspace_disina_cikamaz(tmp_path):
    sonuc = ToolExecutor(tmp_path).check_page("../dis.html")
    assert not sonuc.ok
    assert "HATA" in sonuc.cikti


@tarayici_gerekli
def test_canli_sunucu_url_acilir(tmp_path):
    """check_page http:// URL ile canlı sunucuyu açabilir (React/backend doğrulama)."""
    import socket

    from orchestrator.sunucu import SunucuYoneticisi

    (tmp_path / "index.html").write_text(
        "<!doctype html><title>Canli</title><h1>Canlı Sunucu</h1>", encoding="utf-8"
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    yon = SunucuYoneticisi(tmp_path)
    try:
        yon.baslat(f"python -m http.server {port}", port)
        sonuc = ToolExecutor(tmp_path).check_page(f"http://localhost:{port}")
        assert sonuc.ok, sonuc.cikti
        assert "Canli" in sonuc.cikti  # sayfa başlığı okundu
        assert (tmp_path / ".kontrol" / "canli.png").is_file()
    finally:
        yon.hepsini_durdur()


def test_olmayan_dosya(tmp_path):
    sonuc = ToolExecutor(tmp_path).check_page("yok.html")
    assert not sonuc.ok
    assert "bulunamadı" in sonuc.cikti


# --- dev-server koruması (tarayıcısız: koruma playwright'tan önce devreye girer) ---

_VITE_HTML = (
    '<!doctype html><html><body><div id="root"></div>'
    '<script type="module" src="/src/main.jsx"></script></body></html>'
)


def test_vite_projesi_file_ile_acilamaz(tmp_path):
    """package.json vite'a işaret ediyorsa file:// doğrulaması reddedilir."""
    (tmp_path / "package.json").write_text(
        '{"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5.0.0"}}',
        encoding="utf-8",
    )
    (tmp_path / "index.html").write_text(_VITE_HTML, encoding="utf-8")
    sonuc = ToolExecutor(tmp_path).check_page("index.html")
    assert not sonuc.ok
    assert "start_server" in sonuc.cikti  # modele doğru akış söylenir
    assert "http://localhost" in sonuc.cikti


def test_alt_klasordeki_html_ust_package_jsonu_gorur(tmp_path):
    """package.json köke, HTML alt klasöre yazılsa da koruma çalışır."""
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "next dev"}}', encoding="utf-8")
    alt = tmp_path / "public"
    alt.mkdir()
    (alt / "index.html").write_text("<html><body>x</body></html>", encoding="utf-8")
    sonuc = ToolExecutor(tmp_path).check_page("public/index.html")
    assert not sonuc.ok
    assert "start_server" in sonuc.cikti


def test_mutlak_modul_scripti_package_json_olmadan_da_yakalanir(tmp_path):
    """package.json yoksa bile src="/..." modülü file:// altında kırılır — reddedilir."""
    (tmp_path / "index.html").write_text(_VITE_HTML, encoding="utf-8")
    sonuc = ToolExecutor(tmp_path).check_page("index.html")
    assert not sonuc.ok
    assert "start_server" in sonuc.cikti


def test_statik_sayfa_engellenmez(tmp_path):
    """Göreli yollu düz statik sayfa korumaya takılmaz."""
    (tmp_path / "sayfa.html").write_text(
        '<!doctype html><html><body><script src="app.js"></script></body></html>',
        encoding="utf-8",
    )
    executor = ToolExecutor(tmp_path)
    assert executor._dev_server_gerekli(tmp_path / "sayfa.html", "sayfa.html") is None


def test_dev_sinyalsiz_package_json_engellenmez(tmp_path):
    """package.json var ama dev-server işareti yoksa (düz node paketi) engel yok."""
    (tmp_path / "package.json").write_text('{"name": "arac", "version": "1.0.0"}', encoding="utf-8")
    (tmp_path / "sayfa.html").write_text("<html><body>x</body></html>", encoding="utf-8")
    executor = ToolExecutor(tmp_path)
    assert executor._dev_server_gerekli(tmp_path / "sayfa.html", "sayfa.html") is None


def test_protokol_goreli_url_yanlis_alarm_vermez(tmp_path):
    """src="//cdn..." (protokol-göreli) kökten mutlak sayılmaz."""
    (tmp_path / "s.html").write_text(
        '<html><body><script type="module" src="//cdn.ornek.com/x.js"></script></body></html>',
        encoding="utf-8",
    )
    executor = ToolExecutor(tmp_path)
    assert executor._dev_server_gerekli(tmp_path / "s.html", "s.html") is None


@tarayici_gerekli
def test_gorsel_analiz_rapora_eklenir(tmp_path, monkeypatch):
    (tmp_path / "s.html").write_text("<html><body>x</body></html>", encoding="utf-8")
    monkeypatch.setenv("FCC_GORSEL", "1")
    monkeypatch.setattr(gorsel, "_gemini_anahtari", lambda: "test-anahtar")
    monkeypatch.setattr(
        gorsel, "gorsel_analiz", lambda yol, soru=gorsel.VARSAYILAN_SORU: "1. Başlık taşıyor"
    )
    sonuc = ToolExecutor(tmp_path).check_page("s.html")
    assert "Görsel analiz (Gemini):" in sonuc.cikti
    assert "Başlık taşıyor" in sonuc.cikti


# --- gorsel yardımcıları (ağsız) ---

def test_gorsel_analiz_sahte_http(tmp_path, monkeypatch):
    png = tmp_path / "e.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nsahte")

    class SahteYanit:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "Görsel sorun yok"}]}}]}

    monkeypatch.setattr(gorsel, "_gemini_anahtari", lambda: "k")
    monkeypatch.setattr(gorsel.httpx, "post", lambda *a, **k: SahteYanit())
    assert gorsel.gorsel_analiz(png) == "Görsel sorun yok"


def test_gorsel_analiz_anahtarsiz_none(tmp_path, monkeypatch):
    monkeypatch.setattr(gorsel, "_gemini_anahtari", lambda: None)
    assert gorsel.gorsel_analiz(tmp_path / "yok.png") is None
    assert gorsel.gorsel_acik() is False
