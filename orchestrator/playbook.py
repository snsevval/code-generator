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

# Her tarifte geçen evrensel kurallar (test izolasyonu + pytest disiplini).
_ORTAK_KURALLAR = """
[SİSTEM TARİFİ — bu akışa birebir uy]
- Testler İZOLE olmalı: backend bellekte durum tutuyorsa (liste/sayaç), her testten
  ÖNCE sıfırla. DOĞRU desen — MODÜL niteliğini değiştir (import backend; backend.X = ...):
      import backend
      @pytest.fixture(autouse=True)
      def _sifirla():
          backend.todos.clear()
          backend.next_id = 1
  YANLIŞ: `global next_id; next_id = 1` — bu import edilen adı yeniden bağlar,
  backend.next_id'yi DEĞİŞTİRMEZ; durum sızar ve testler yanlış patlar (canlıda görüldü).
- pytest başarısız olursa PANİKLEME: assert satırını OKU ve KODU düzelt. Ortam değişkeni,
  paket veya eklenti KURCALAMA — sorun kodda, çalıştırma ortamında değil.
"""

# Yalnız ARAÇ kullanan (sunucuyu KENDİ başlatan) tarifler için — vite/frontend.
# backend/fullstack file-only olduğundan (sunucuyu sistem başlatır) bu kurallar
# onlara EKLENMEZ; aksi halde model olmayan araçları çağırmaya çalışır.
_SUNUCU_KURALLARI = f"""
- Portlar sabittir: backend {BACKEND_PORT}, frontend {FRONTEND_PORT}. Başka port deneme.
- Sunucu başlatma YALNIZCA start_server ile (run_shell'de start /b, & vb. YASAK).
  start_server çağrısı iki alan ister; örnek: {{"command": "uvicorn backend:app --port {BACKEND_PORT}", "port": {BACKEND_PORT}}}
- Bir sunucuyu başlat-durdur döngüsüne sokma: bir kez başlat, tüm doğrulamayı yap, en sonda durdur.
- İş bitince açtığın HER sunucuyu stop_server ile durdur.
"""

_PLAYBOOKLAR: dict[str, str] = {
    "fullstack": _ORTAK_KURALLAR
    + """
Full-stack (TEK-ORIGIN) — ŞU DOSYALARI YAZ (sistem çalıştırıp doğrular; sen pytest/sunucu/tarayıcı ÇALIŞTIRMA):
1. backend.py: FastAPI; uçlar JSON, veri bellekte. AYRICA index.html'i `/` kökünde SERVİS ET:
       from fastapi.responses import FileResponse
       @app.get("/")
       def index():
           return FileResponse("index.html")
   Frontend ve API aynı origin'de olacağı için CORS ve sabit port GEREKMEZ.
2. test_backend.py: pytest + fastapi.testclient.TestClient ile TÜM uçları test et.
   Testler İZOLE: autouse fixture ile her testten önce 'import backend; backend.<liste>.clear();
   backend.<sayaç> = ...' ile sıfırla.
3. index.html: tek dosya, CSS gömülü. fetch'te GÖRELİ yol kullan — fetch('/todos') (sabit
   host/port YAZMA, http://localhost:XXXX YOK). Sayfa yüklenince GET ile listeyi çek ve DOM'a
   BAS; ekle POST, sil DELETE. Frontend backend'in özelliğini YANSITMALI (sayaç değil, backend neyse o).
ZORUNLU: Sistem backend'i BOŞ bir portta başlatır (index.html'i de o servis eder), sayfayı açıp
frontend'in backend'e GERÇEKTEN fetch atıp veri çektiğini AĞ düzeyinde kontrol eder — backend'e
istek atmayan bağımsız/sahte sayfa GEÇMEZ. Sen sadece 3 dosyayı yaz.
""",
    "backend": _ORTAK_KURALLAR
    + """
Backend — ŞU DOSYALARI YAZ (sistem çalıştırıp doğrular; sen pytest/sunucu ÇALIŞTIRMA):
1. backend.py: FastAPI; uçlar JSON, veri bellekte. Frontend erişecekse CORSMiddleware ekle
   (allow_origins=["*"]).
2. test_backend.py: pytest + TestClient ile TÜM uçları test et. Testler İZOLE: autouse fixture
   ile her testten önce 'import backend; backend.<liste>.clear(); backend.<sayaç> = ...' ile sıfırla.
Sistem: pytest'i izole (PYTEST_DISABLE_PLUGIN_AUTOLOAD) koşar ve uvicorn'u başlatıp uçları
doğrular. Sen sadece 2 dosyayı yaz, kısa özetle bitir.
""",
    "vite": _ORTAK_KURALLAR
    + _SUNUCU_KURALLARI
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
    + _SUNUCU_KURALLARI
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
