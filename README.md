# code-generator

[free-claude-code](https://github.com/Alishahryar1/free-claude-code) proxy'sini LLM erişim
katmanı olarak kullanan agentic kod üretim ürünü. Ayrıntılı yol haritası:
[docs/task_plan.md](docs/task_plan.md)

## Kurulum

```powershell
uv sync
```

## Faz 0 — Tool-use tutarlılık testi

Önce proxy'yi ayrı bir terminalde başlatın (`http://localhost:8082` üzerinde çalışmalı):

```powershell
fcc-server
```

Sonra testi çalıştırın:

```powershell
# Ayrıntılı rapor ile (önerilen) — model açıkça belirtilmeli, bkz. docs/task_plan.md bulguları
$env:FCC_TEST_MODEL = 'gemini/gemini-2.5-flash'
uv run python tests/test_tool_use_consistency.py

# veya pytest ile
uv run pytest tests/test_tool_use_consistency.py -s
```

Ortam değişkenleri: `FCC_TEST_MODEL` (model, `provider/model` biçimi doğrudan yönlendirir),
`FCC_TEST_REPEAT` (deneme sayısı, varsayılan 10), `FCC_TEST_DELAY` (denemeler arası saniye,
varsayılan 5), `ANTHROPIC_AUTH_TOKEN` (proxy giriş anahtarı; proxy'deki `~/.fcc/.env` ile
aynı olmalı, varsayılan `freecc`).

Script aynı tool tanımlı isteği proxy'ye 10 kez gönderir; her cevapta `tool_use` bloğunun
varlığını, tool adının doğruluğunu (`read_file`) ve zorunlu `path` parametresinin geçerliliğini
kontrol eder. Sonunda `X/10 başarılı` özeti ve başarısızlıkların hata tipi dağılımını basar.

## Faz 2 — Agentic döngü

Proxy açıkken bir görevi uçtan uca çalıştırmak için:

```powershell
uv run python -m orchestrator "fibonacci hesaplayan küçük bir CLI aracı yaz"

# Seçenekler:
#   --workspace <klasör>  çalışma alanı (varsayılan: workspace)
#   --docker              run_shell komutlarını ağa kapalı Docker sandbox'ta koşar
#   --devam               kesilen görevi .state/oturum.json'dan sürdürür
#   --proje               büyük hedef modu: Decomposer hedefi alt görevlere böler,
#                         her biri tam döngüyle sırayla koşulur (Faz 4)
```

Akış: Planner → Codegen → Test/Validator → (başarısızsa Debugger, en çok 3 tur) → Reviewer.
Model seçimi: `FCC_MODEL` tüm ajanları, `FCC_MODEL_PLANNER` gibi değişkenler tek ajanı
değiştirir (varsayılan: `gemini/gemini-2.5-flash`).

## Faz 3 — Web arayüzü

İki sunucu gerekir (proxy'ye ek olarak):

```powershell
# 1) Backend API (proje kökünde)
uv run uvicorn orchestrator.api:app --port 8090

# 2) Next.js arayüzü
cd ui
npm run dev
```

Sonra http://localhost:3000 — görev yaz, modeli seç, ajanların ilerleyişini canlı izle.

## Proje yapısı

| Klasör          | İçerik                                              |
| --------------- | --------------------------------------------------- |
| `orchestrator/` | Orkestratör, Tool Executor ve ajanlar (Faz 1–2)     |
| `tests/`        | Testler                                             |
| `workspace/`    | Ajanların üzerinde çalışacağı izole çalışma alanı   |
| `docs/`         | Plan ve dokümantasyon                               |
