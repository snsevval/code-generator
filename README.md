# code-generator

Doğal dille verilen görevi alıp kodu kendi yazan, test eden, hatasını düzeltip çalıştırarak
doğrulayan çok-ajanlı kod üretim sistemi. LLM erişimi
[free-claude-code](https://github.com/Alishahryar1/free-claude-code) proxy'si üzerinden
sağlanır (NVIDIA NIM / Gemini / Groq).

Her çıktı gerçekten çalıştırılır; testler koşulur, sunucu ayağa kaldırılır, sayfa tarayıcıda açılıp
backend bağlantısı ağ düzeyinde doğrulanır.

Ayrıntılı dokümantasyon: [docs/PROJE_RAPORU.md](docs/PROJE_RAPORU.md) ·
[docs/DURUM.md](docs/DURUM.md) · [docs/task_plan.md](docs/task_plan.md)

🌐 Canlı dokümantasyon: https://snsevval.github.io/code-generator-doc/

## Özellikler

- **Altı uzman ajan:** Planner, Codegen, Validator, Debugger, Reviewer, Decomposer —
  hepsi aynı modele verilen farklı rol talimatları.
- **Deterministik doğrulama (Runner):** backend görevlerinde pytest izole koşulur
  (`PYTEST_DISABLE_PLUGIN_AUTOLOAD`) ve uvicorn ayağa kaldırılır; full-stack görevlerde
  frontend tarayıcıda açılıp backend'e gerçekten fetch attığı ağ düzeyinde kanıtlanır.
  Backend'e bağlanmayan sayfa geçemez.
- **Tek-origin full-stack:** backend `index.html`'i kök dizinden servis eder, frontend
  göreli `fetch` kullanır — sabit port ve CORS gerekmez.
- **Dosya-odaklı ajanlar:** backend/full-stack görevlerinde Codegen ve Debugger yalnızca
  dosya yazar/düzenler; test koşma, sunucu yönetimi ve doğrulama tamamen sisteme aittir
  (zayıf modellerin kabuk/ortam debelenmesi mekanik olarak engellenir).
- **Takip modu (iteratif geliştirme):** proje bitince aynı oturumda "arka planı değiştir",
  "buton ekle" gibi isteklerle aynı proje üzerinde devam edilir; mevcut dosyalar korunur,
  sistem bağlamı (dosya listesi + istek geçmişi) otomatik ekler.
- **Kalıcı canlı önizleme:** başarılı görevden sonra üretilen backend dinamik bir portta
  açık kalır; göz simgesi çalışan uygulamayı açar. `/onizle/*.html` istekleri canlı
  backend'e otomatik yönlendirilir.
- **Değişiklik geçmişi:** her görev kendi klasöründe git ile kaydedilir;
  `GET /api/degisiklikler` son değişikliği gösterir, `POST /api/geri-al` geri alır.
- **Playbook katmanı:** görev tipi (backend / full-stack / vite / frontend) otomatik
  tanınır; portlar, dosya listesi ve doğrulama tarifi göreve sistem tarafından eklenir —
  kullanıcı teknik ayrıntı yazmaz.
- **Mekanik korumalar:** izole görev klasörleri, sahte-başarı engeli, boş-çıktı dürtüsü,
  tekrar kilidi, debelenme detektörü, ortam-kurcalama reddi (pip un/install, eklenti
  kapatma), arka plan süreç reddi ve diğerleri — her biri gerçek bir kazadan doğdu.

## Kurulum

```powershell
uv sync
uv run playwright install chromium   # tarayıcı doğrulaması için
```

## Çalıştırma

Üç sunucu gerekir:

```powershell
# 1) LLM proxy (ayrı klasördeki free-claude-code projesinden)
cd C:\...\free-claude-code
uv run fcc-server                    # http://localhost:8082

# 2) Backend API (bu projenin kökünde)
uv run uvicorn orchestrator.api:app --port 8090

# 3) Web arayüzü
cd ui
npm run dev                          # http://localhost:3000
```

Sonra http://localhost:3000 adresinde görevi doğal dille yaz, ajan akışını canlı izle,
bitince "Projeye devam et" kutusundan aynı proje üzerinde değişiklik iste.

Örnek görev:

```
Basit bir görev listesi (todo) full-stack uygulaması yap: FastAPI backend görev ekleme,
listeleme ve silme uçlarıyla; tek sayfalık arayüz backend'e fetch ile bağlanıp listeyi
göstersin, ekleme ve silme yapsın; pytest ile test et.
```

Komut satırından kullanım:

```powershell
uv run python -m orchestrator "fibonacci hesaplayan küçük bir CLI aracı yaz"

# Seçenekler:
#   --workspace <klasör>  çalışma alanı (varsayılan: workspace)
#   --docker              run_shell komutlarını ağa kapalı Docker sandbox'ta koşar
#   --devam               kesilen görevi kaldığı yerden sürdürür
#   --proje               büyük hedef modu: hedef alt görevlere bölünüp sırayla koşulur
```

## Model seçimi

İstekler proxy'nin varsayılan rotasına gider (`~/.fcc/.env` içindeki `MODEL`; şu an
NVIDIA NIM Nemotron). Ortam değişkenleriyle değiştirilebilir:

- `FCC_MODEL` — tüm ajanlar için model (`provider/model` biçimi doğrudan yönlendirir)
- `FCC_MODEL_CODEGEN` gibi ajan-özel değişkenler tek ajanı değiştirir
- `ANTHROPIC_AUTH_TOKEN` — proxy giriş anahtarı (proxy'deki `~/.fcc/.env` ile aynı olmalı)

Yeni bir model kullanmadan önce tutarlılık kapısından geçirin (10/10 geçerli tool-use
beklenir):

```powershell
$env:FCC_TEST_MODEL = 'nvidia_nim/deepseek-ai/deepseek-v4-flash'
uv run python tests/test_tool_use_consistency.py
```

## Testler

```powershell
uv run pytest          # tam paket (200+ test; proxy gerektirenler otomatik atlanır)
```

## Proje yapısı

| Klasör / dosya                     | İçerik                                                            |
| ---------------------------------- | ----------------------------------------------------------------- |
| `orchestrator/loop.py`             | Orkestratör: ajan döngüsü, aşama akışı, mekanik korumalar         |
| `orchestrator/agents.py`           | Ajan tanımları (prompt, araç listesi, model rotası)               |
| `orchestrator/tool_executor.py`    | Araçlar: dosya, kabuk, tarayıcı, sunucu (workspace'e hapsedilmiş) |
| `orchestrator/fullstack_runner.py` | Deterministik doğrulama: pytest + uvicorn + entegrasyon kanıtı    |
| `orchestrator/playbook.py`         | Görev tipi tespiti ve teknik tarif enjeksiyonu                    |
| `orchestrator/api.py`              | Web arayüzünün konuştuğu FastAPI (görev, takip, önizleme, geri-al)|
| `orchestrator/sunucu.py`           | Arka plan süreç yönetimi, dinamik port, sızıntı önleme            |
| `ui/`                              | Next.js arayüzü (görev, canlı log, dosyalar, takip)               |
| `tests/`                           | Test paketi                                                       |
| `workspace/`                       | Görev başına izole çalışma klasörleri                             |
| `docs/`                            | Rapor, durum ve yol haritası                                      |
