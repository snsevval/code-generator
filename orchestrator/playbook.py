"""Faz 9 — Playbook katmanı: teknik tarifi sistem ekler, kullanıcı değil.

Kullanıcı yalnızca NE istediğini söyler ("full-stack sayaç uygulaması");
portlar, araç akışı (start_server/check_page/stop_server), doğrulama adımları
gibi mühendislik bilgisi buradaki test edilmiş tariflerden görev metnine
otomatik enjekte edilir. Tarifler, canlıda geçen koşuların görev metinlerinden
türetildi — modelin geçmişte savrulduğu her nokta (port dansı, start /b,
file:// doğrulaması) tarifte sabitlenmiştir.

Tespit deterministiktir (anahtar kelime; LLM çağrısı yok, kotasız).
"""

from __future__ import annotations

import re

# Port konvansiyonları — model seçim yapmasın diye sabit
BACKEND_PORT = 8123
FRONTEND_PORT = 8200

_ORTAK_KURALLAR = f"""
[SİSTEM TARİFİ — bu akışa birebir uy]
- Portlar sabittir: backend {BACKEND_PORT}, frontend {FRONTEND_PORT}. Başka port deneme.
- Sunucu başlatma YALNIZCA start_server ile (run_shell'de start /b, & vb. YASAK).
  start_server çağrısı iki alan ister; örnek: {{"command": "uvicorn backend:app --port {BACKEND_PORT}", "port": {BACKEND_PORT}}}
- Bir sunucuyu başlat-durdur döngüsüne sokma: bir kez başlat, tüm doğrulamayı yap, en sonda durdur.
- İş bitince açtığın HER sunucuyu stop_server ile durdur.
"""

_PLAYBOOKLAR: dict[str, str] = {
    "fullstack": _ORTAK_KURALLAR
    + f"""
Full-stack akışı — sırasıyla:
1. backend.py: FastAPI + CORSMiddleware (allow_origins=["*"], allow_methods=["*"],
   allow_headers=["*"]). Uçlar isteğe göre; cevaplar JSON. Veri bellekte (global değişken).
2. test_backend.py: pytest + fastapi.testclient.TestClient ile TÜM uçları test et;
   run_shell 'python -m pytest test_backend.py -v' ile koş. (Sunucu başlatmadan çalışır.)
3. index.html: tek dosya, CSS gömülü; fetch ile http://localhost:{BACKEND_PORT} uçlarına
   bağlanır. Sayfa yüklenince veriyi çekip gösterir; butonlar POST atıp görünümü günceller.
4. CANLI DOĞRULAMA (tek turda, başlat-durdur zikzakı YOK):
   a. start_server {{"command": "uvicorn backend:app --port {BACKEND_PORT}", "port": {BACKEND_PORT}}}
   b. start_server {{"command": "python -m http.server {FRONTEND_PORT}", "port": {FRONTEND_PORT}}}
   c. run_shell curl ile uçları dene (örn. POST sonrası GET değişimi doğrula)
   d. check_page http://localhost:{FRONTEND_PORT}/index.html — konsol hatasız olmalı,
      sayfada backend'den gelen veri görünmeli
   e. stop_server {FRONTEND_PORT}, stop_server {BACKEND_PORT}
""",
    "backend": _ORTAK_KURALLAR
    + f"""
Backend akışı — sırasıyla:
1. backend.py: FastAPI; uçlar isteğe göre, cevaplar JSON, veri bellekte.
   Frontend'den erişilecekse CORSMiddleware ekle (allow_origins=["*"]).
2. test_backend.py: pytest + TestClient ile tüm uçları test et;
   run_shell 'python -m pytest test_backend.py -v' ile koş.
3. CANLI DOĞRULAMA: start_server {{"command": "uvicorn backend:app --port {BACKEND_PORT}", "port": {BACKEND_PORT}}},
   run_shell curl ile uçları dene, stop_server {BACKEND_PORT}.
""",
    "vite": _ORTAK_KURALLAR
    + f"""
Vite/React proje akışı — sırasıyla:
1. Dosyaları yaz: package.json (dev script: "vite"), vite.config.js
   (MUTLAKA — @vitejs/plugin-react plugin'li, server.port: {FRONTEND_PORT}),
   index.html, src/main.jsx, src/App.jsx. JSX'te React import gerekmez
   (plugin otomatik runtime sağlar) ama vite.config.js olmadan ÇALIŞMAZ.
2. run_shell 'npm install' (timeout=600).
3. CANLI DOĞRULAMA: start_server {{"command": "npm run dev", "port": {FRONTEND_PORT}}},
   check_page http://localhost:{FRONTEND_PORT} (dosya yolu DEĞİL — file:// altında
   modüller yüklenmez), stop_server {FRONTEND_PORT}.
""",
    "frontend": _ORTAK_KURALLAR
    + f"""
Statik sayfa akışı — sırasıyla:
1. index.html: tek dosya, CSS/JS gömülü (harici derleme yok). React istenirse
   CDN'den (unpkg react + react-dom + @babel/standalone, script type="text/babel").
2. DOĞRULAMA: check_page index.html (statik dosya için dosya yolu yeterli) —
   konsol hatasız olmalı, görsel analiz bulgularını edit_file ile düzelt.
""",
}

# Tespit desenleri (küçük harfe indirgenmiş metinde aranır)
_BACKEND_SINYALI = re.compile(r"backend|fastapi|flask|api uç|endpoint|sunucu taraf|rest ")
_FRONTEND_SINYALI = re.compile(r"frontend|arayüz|sayfa|site|html|görsel|tasarım|ön yüz|ui")
_VITE_SINYALI = re.compile(r"\bvite\b|\bnext\.?js\b|npm|gerçek react projesi")
_FULLSTACK_SINYALI = re.compile(r"full[ -]?stack|fullstack")


def playbook_sec(gorev: str) -> str | None:
    """Görev metnine uygun playbook adını döndürür (yoksa None)."""
    metin = gorev.lower()
    backend = bool(_BACKEND_SINYALI.search(metin))
    frontend = bool(_FRONTEND_SINYALI.search(metin))
    if _FULLSTACK_SINYALI.search(metin) or (backend and frontend):
        return "fullstack"
    if _VITE_SINYALI.search(metin):
        return "vite"
    if backend:
        return "backend"
    if frontend:
        return "frontend"
    return None


def gorevi_zenginlestir(gorev: str) -> tuple[str, str | None]:
    """Görev metnine uygun tarifi ekler; (yeni_metin, playbook_adi) döndürür."""
    ad = playbook_sec(gorev)
    if ad is None:
        return gorev, None
    return gorev + "\n" + _PLAYBOOKLAR[ad], ad
