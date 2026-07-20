# Proje Durumu — Agentic Kod Üretim Ürünü

> Son güncelleme: 2026-07-20 · Ayrıntılı faz geçmişi: [task_plan.md](task_plan.md)

## Bu proje ne?

Doğal dille (Türkçe) görev alan, kodu **kendi yazan, test eden, hatasını düzelten ve
raporlayan** çok-ajanlı bir kod üretim sistemi. LLM erişimi
[free-claude-code](https://github.com/Alishahryar1/free-claude-code) proxy'si üzerinden
(Anthropic Messages API biçimi → NVIDIA NIM / Gemini / Groq'a yönlendirme).

```
Kullanıcı (UI :3000 / CLI)
   → Backend API (:8090, FastAPI)
      → Orkestratör (ajan döngüsü + korumalar + playbook enjeksiyonu)
         → Ajanlar: Planner → Codegen → (Validator) → (Debugger) → Reviewer
         → Deterministik Runner: pytest / uvicorn / tarayıcı / g++  (backend·fullstack·cpp)
            → Araçlar (ToolExecutor, workspace'e hapsedilmiş)
               → LLM: proxy (:8082) → NIM Nemotron (varsayılan) / Gemini / Groq
```

## Merkezdeki mimari: doğrulamayı modelden al, orkestratöre ver

Zayıf modeller (Nemotron) tek dosyalı işleri iyi yapar ama çok-dosyalı, çok-adımlı
doğrulamada savrulur: sahte "BAŞARILI" der, test/sunucu koreografisinde debelenir,
docker halüsinasyonuna kapılır. Çözüm: **test etme, sunucu yönetme ve doğrulamayı
tamamen sisteme almak.** Model yalnızca dosyaları yazar; sistem deterministik doğrular.

- **Backend:** izole pytest + uvicorn'u ayağa kaldır + `/openapi.json` serve kontrolü.
- **Full-stack (tek-origin):** backend `index.html`'i `/` kökünde servis eder, frontend
  **göreli** `fetch('/...')` kullanır; sistem dinamik portta başlatır, tarayıcıda açıp
  frontend'in backend'e **gerçekten fetch attığını AĞ düzeyinde** kanıtlar. Buton-tetikli
  formlarda girdileri doldurup butona tıklar. Backend'e bağlanmayan sayfa GEÇMEZ.
- **C++:** `g++ -std=c++17 -static` ile derle (asıl sınav — tip/typo/`M_PI` hataları
  burada yakalanır), sonra çalıştır. Model-validator döngüsü yerine mekanik doğrulama.

Backend/fullstack/cpp görevlerinde Codegen ve Debugger **yalnızca dosya araçları** alır
(write/edit/read/list/search) — kabuk/sunucu/derleyici debelenmesi mekanik olarak imkânsız.

## Playbook katmanı — teknik tarifi sistem ekler, kullanıcı değil

Görev metninden tip otomatik tanınır (backend / fullstack / cpp / vite / frontend) ve
göreve dosya listesi + doğrulama tarifi + bilinen tuzak uyarıları eklenir. Kullanıcı
"FastAPI, port, CORS" yazmaz — "bir todo uygulaması yap" der, gerisini sistem tarifler.
Tarifteki önleme kuralları (canlı kazalardan doğdu): POST gövdesi **Pydantic BaseModel**
(query/422 tuzağı), **JS'te değişkeni kullanmadan önce tanımla** (TDZ çökmesi), **float
testte `==` yok, `pytest.approx`** (kayan nokta kırılması), tek-origin göreli fetch.

## Takip modu — aynı proje üzerinde sohbet gibi devam

Görev bitince "arka planı koyu yap", "giriş sayfası ekle" gibi isteklerle **aynı klasörde**
devam edilir: mevcut dosyalar korunur, sistem bağlamı (dosya listesi + istek geçmişi)
otomatik eklenir, doğrulama tipi ilk görevden miras kalır. Başarılı görevden sonra
backend dinamik bir portta canlı kalır (göz ikonu çalışan uygulamayı açar); değişiklikler
git ile kaydedilir (**Değişiklikleri Gör** = diff, **Geri Al** = revert). Çalışan görev
**İptal** butonuyla durdurulabilir (işbirlikçi: bir sonraki aşamada temiz durur).

## Dosya yapısı

| Dosya | Görev |
|---|---|
| `orchestrator/loop.py` | Orkestratör: tool döngüsü, debugger↔doğrulama döngüsü, tüm mekanik korumalar, iptal |
| `orchestrator/fullstack_runner.py` | **Deterministik Runner**: pytest + uvicorn + tarayıcı entegrasyonu + g++ (backend/fullstack/cpp) |
| `orchestrator/playbook.py` | Görev tipi tespiti + teknik tarif/tuzak-uyarısı enjeksiyonu |
| `orchestrator/agents.py` | 6 ajan tanımı, sistem promptları, model routing (`FCC_MODEL[_AJAN]`) |
| `orchestrator/tool_executor.py` | 11 araç + guard'lar (ortam-kurcalama, paket-kurulum, geçersiz path reddi) |
| `orchestrator/llm_client.py` | Proxy istemcisi: backoff'lu yeniden deneme, token sayacı |
| `orchestrator/proje.py` | Proje modu: Decomposer → alt görev zinciri → final entegrasyon doğrulaması |
| `orchestrator/state.py` | OturumState + ProjeState (kesintiden `--devam`) |
| `orchestrator/api.py` | FastAPI: görev/durum/onay/iptal, takip, dosya listeleme/indirme, `/onizle` yönlendirme, diff/geri-al |
| `orchestrator/sunucu.py` | Arka plan süreç yönetimi + dinamik boş-port bulucu (IPv4+IPv6; ağaç öldürme) |
| `orchestrator/gorsel.py` | Screenshot'ı Gemini'yle analiz (karma model: ajanlar NIM'de kalır) |
| `orchestrator/tasarim.py` | ui-ux-pro-max tasarım sistemini görev metnine enjekte eder |
| `orchestrator/git_deposu.py` | Görev klasöründe otomatik git (kendi reposu; üst repoya bulaşmaz) |
| `orchestrator/calisma_alani.py` | Görev başına izole klasör (`workspace/gorev-*`); takipte aynı klasör |
| `ui/` | Next.js panosu (ajan akış şeridi, canlı log, token halkası, dosya/önizleme, takip, iptal) |
| `tests/` | ~238 test (çoğu ağsız/kotasız; proxy/playwright/g++ yoksa ilgili testler atlanır) |

## Nasıl çalıştırılır

```powershell
# 1) Proxy (ayrı terminal) — LLM erişim katmanı
cd C:\Users\sevval\Desktop\free-claude-code
uv run fcc-server                                    # :8082, admin: /admin

# 2) Backend API (proje kökünde; token proxy'ninkiyle aynı olmalı)
uv run uvicorn orchestrator.api:app --port 8090

# 3) Arayüz
cd ui && npm run dev                                 # :3000

# CLI alternatifi
uv run python -m orchestrator "görev" [--proje] [--tasarim] [--devam] [--docker]

# Testler
uv run pytest
# C++ görevleri için (opsiyonel): bir g++ derleyicisi PATH'te olmalı
```

Arayüz anahtarları: **Proje modu** (büyük hedefi alt görevlere böler), **Adım adım onay**,
**UI görevi** (tasarım sistemi + görsel doğrulama), **Docker sandbox** (KAPALI tut —
imajda node yok; ayrıca güvenlik guard'ları paket kurulumunu engeller).

## Modeller

- **Birincil:** NVIDIA NIM Nemotron (proxy `MODEL` rotası; tool-use 10/10)
- **Görsel analiz:** Gemini 2.5 Flash (doğrudan REST, proxy'den bağımsız; `GEMINI_API_KEY`)
- **Yedek/aday:** Gemini 2.5 Flash, Groq Llama-3.3-70B, NIM DeepSeek-v4-flash (tool-use 10/10)
- Ajan başına: `FCC_MODEL_CODEGEN=...` / `FCC_MODEL_DEBUGGER=...`; tümü: `FCC_MODEL`.
  Yeni model eklerken **önce tutarlılık testinden geçir:**
  `FCC_TEST_MODEL=... uv run python tests/test_tool_use_consistency.py`

## Kanıtlanmış yetenekler

- **Backend (deterministik):** FastAPI + izole pytest + canlı uvicorn serve kontrolü — sahte başarı imkânsız
- **Full-stack (tek-origin):** backend + göreli fetch'li frontend + testler; tarayıcı ağ
  düzeyinde bağlantıyı kanıtlar; buton-tetikli formlarda girdi doldurulur (todo, sıcaklık
  çevirici, oylama — canlı BAŞARILI, önizleme çalışır)
- **C++ (deterministik):** g++ ile derle + çalıştır (uydu yörünge programı — 367k→9k token,
  derleyici avı yok, tek koşuda BAŞARILI)
- **Takip:** aynı proje üzerinde iteratif değişiklik (dosyalar korunur, git diff/geri-al)
- Python CLI + pytest; Proje modu (Decomposer → alt görev zinciri); CDN React / tasarım
  sistemli sayfalar; Vite (npm install + dev server); görsel doğrulama (check_page + Gemini)

## Mekanik korumalar (hepsi gerçek kazalardan doğdu)

**Doğrulama & sahte-başarı:**
1. Deterministik Runner: backend/fullstack/cpp'de model-validator yerine mekanik doğrulama
2. Kanıt şartı: model-validator araç çalıştırmadan karar veremez
3. Takip sahte-başarı kapanı: codegen hiçbir dosyayı değiştirmediyse görev başarılı sayılmaz
4. Reviewer başarısız koşuda atlanır (Runner hatası zaten net; commit yine yapılır)

**Codegen/Debugger disiplini:**
5. File-only ajanlar: backend/fullstack/cpp'de kabuk/sunucu/derleyici araçları kapalı
6. Boş-çıktı dürtüsü: codegen araç kullanıp hiç dosya yazmazsa güçlü dürtüyle tekrar
7. Eksik-dosya dürtüsü: zorunlu dosyalar (index.html, test) eksikse isim isim dürtülür
8. Debugger no-op freni: debug turu hiç dosya değiştirmezse boşa tekrar koşmaz, erken bırakır
9. Tekrar kilidi + debelenme detektörü (aynı araç+girdi / dosyasız ardışık run_shell)

**Güvenlik & sağlamlık:**
10. Ortam-kurcalama reddi: `pip install/uninstall`, `-p no:`, docker env değişkenleri
11. Paket-kurulum yasağı: `winget/choco/scoop/pacman/apt/npm install...` — ajan izinsiz yazılım kuramaz
12. Geçersiz-path reddi: araç-etiketi path'e sızarsa (`<parameter=...>`) görev çökmez, dostça hata
13. Arka plan süreç reddi (`start /b`, `&`) + sunucu sızıntı önleme (görev sonu hepsini kapat)

**Önleme (tarif kuralları) & altyapı:**
14. Pydantic gövde / JS sıralama / float `approx` kuralları tarife gömülü
15. Tek-origin (sabit port/CORS yok) + dinamik boş-port bulucu
16. Buton-tetikli formlarda girdi doldur + butona tıkla (yanlış-başarısız önleme)
17. İzole görev klasörleri; şema uyarısı; git kendi reposu; check_page dev-server koruması;
    işbirlikçi iptal (çalışan görevi temiz durdur)

## KALDIĞIMIZ YER — sıradaki adımlar

1. **Codegen/Debugger'ı güçlü kod modeline al (en yüksek kaldıraç):** Tüm başarısız
   koşuların ortak deseni — Runner hatayı doğru bulur ama Debugger (bir muhakeme işi)
   düzeltemez. Nemotron her koşuda farklı savrulur. `deepseek-v4-flash` tool-use'da 10/10
   verdi; kod değişmeden `FCC_MODEL_DEBUGGER` ile denenebilir. Mekanik guard'lar semptomu
   sınırlar; kalıcı çözüm bu.
2. Faz 6 (planlandı): API bağlama — sır yönetimi (.env enjeksiyonu), pip/npm bağımlılık
   politikası, Docker'da seçmeli ağ.
3. Görev kuyruğu, model karşılaştırma raporu.

## Bilinen kısıtlar / notlar

- Nemotron: tek dosyalı işlerde (backend, C++) güvenilir; çok-dosyalı full-stack'te ara sıra
  savrulur (yanlış içerik, eksik dosya, kırılgan test) — mekanik guard'lar + tarif kuralları
  hasarı sınırlar, kalıcı çözüm madde 1.
- C++ görevleri için makinede bir g++ derleyicisi gerekir (yoksa Runner "derleyici yok,
  kullanıcı kurmalı" der — ajan kuramaz, güvenlik guard'ı engeller).
- Full-stack önizleme başarılı görevden sonra dinamik portta açılır; `/onizle/*.html`
  otomatik canlı backend'e yönlenir. Tarayıcı bayat hali önbelleğe aldıysa **Ctrl+Shift+R**.
- Docker imajı `python:3.12-slim` — node yok; UI/Vite görevlerinde Docker anahtarı kapalı olmalı.
