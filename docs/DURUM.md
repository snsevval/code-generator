# Proje Durumu — Agentic Kod Üretim Ürünü

> Son güncelleme: 2026-07-16 · Ayrıntılı faz geçmişi: [task_plan.md](task_plan.md)

## Bu proje ne?

Doğal dille (Türkçe) görev alan, kodu **kendi yazan, test eden, hatasını düzelten ve
raporlayan** çok-ajanlı bir kod üretim sistemi. LLM erişimi
[free-claude-code](https://github.com/Alishahryar1/free-claude-code) proxy'si üzerinden
(Anthropic Messages API biçimi → NVIDIA NIM / Gemini / Groq'a yönlendirme).

```
Kullanıcı (UI :3000 / CLI)
   → Backend API (:8090, FastAPI)
      → Orkestratör (ajan döngüsü + korumalar)
         → Ajanlar: Planner → Codegen → Validator → (Debugger) → Reviewer
            → Araçlar (ToolExecutor, workspace'e hapsedilmiş)
               → LLM: proxy (:8082) → NIM Nemotron (varsayılan) / Gemini / Groq
```

## Dosya yapısı

| Dosya | Görev |
|---|---|
| `orchestrator/loop.py` | Orkestratör: tool döngüsü, debugger↔validator döngüsü, tüm mekanik korumalar |
| `orchestrator/agents.py` | 6 ajan tanımı (5 + Decomposer), sistem promptları, model routing (`FCC_MODEL[_AJAN]`) |
| `orchestrator/tool_executor.py` | 10 araç: list/search/read/write/edit_file, run_shell, check_page, start/stop_server, server_log |
| `orchestrator/llm_client.py` | Proxy istemcisi: backoff'lu yeniden deneme, token sayacı |
| `orchestrator/proje.py` | Proje modu: Decomposer → alt görev zinciri → final entegrasyon doğrulaması |
| `orchestrator/state.py` | OturumState + ProjeState (kesintiden `--devam`) |
| `orchestrator/api.py` | FastAPI: görev başlat/durum/onay, dosya listeleme/indirme, statik `/onizle`, canlı önizleme |
| `orchestrator/sunucu.py` | Arka plan süreç yönetimi (dev sunucular; IPv4+IPv6 port kontrolü; ağaç öldürme) |
| `orchestrator/gorsel.py` | Screenshot'ı Gemini'yle analiz (karma model: ajanlar NIM'de kalır) |
| `orchestrator/tasarim.py` | ui-ux-pro-max tasarım sistemini görev metnine enjekte eder |
| `orchestrator/indeks.py` | Repo indeksi: TF-IDF (varsayılan) / Gemini embedding (`FCC_EMBEDDING=gemini`) |
| `orchestrator/git_deposu.py` | Görev klasöründe otomatik git (kendi reposu; üst repoya bulaşmaz) |
| `orchestrator/calisma_alani.py` | Görev başına izole klasör (`workspace/gorev-*`) |
| `ui/` | Next.js 16 panosu (mor/indigo, ajan akış şeridi, canlı log, token halkası, dosya/önizleme) |
| `tests/` | ~145 test (çoğu ağsız/kotasız; proxy/playwright yoksa atlanır) |

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
```

Arayüz anahtarları: **Proje modu** (büyük hedefi alt görevlere böler), **Adım adım onay**,
**UI görevi** (tasarım sistemi + görsel doğrulama), **Docker sandbox** (node gerektiren
işlerde KAPALI tut — imajda node yok).

## Modeller

- **Birincil:** NVIDIA NIM `nemotron-3-super-120b-a12b` (proxy `MODEL` rotası; tool-use 10/10)
- **Görsel analiz:** Gemini 2.5 Flash (doğrudan REST, proxy'den bağımsız; `GEMINI_API_KEY`)
- **Yedek:** Gemini 2.5 Flash (günde ~250 istek), Groq Llama-3.3-70B (100k token/gün)
- Ajan başına: `FCC_MODEL_CODEGEN=...` gibi; tümü: `FCC_MODEL`. Yeni model eklerken
  **önce tutarlılık testinden geçir:** `FCC_TEST_MODEL=... uv run python tests/test_tool_use_consistency.py`

## Kanıtlanmış yetenekler

- Python CLI araçları + pytest (fibonacci, şifre üreteci — insansız, 0 debug turu koşular var)
- Proje modu: not defteri uygulaması 4/4 alt görev + entegrasyon doğrulaması
- Frontend: CDN React, çok dosyalı HTML/CSS/JS, tasarım sistemli sayfalar (fiyat, portfolyo)
- Görsel doğrulama: check_page + Gemini, gömülü kusurları (kontrast/taşma) yakaladı
- **Vite**: npm install + dev server çalışıyor (mekanizma; IPv6 fix sonrası kanıtlı)
- **Backend (AJANLAR, 2026-07-16)**: FastAPI + pytest + start_server/uvicorn + curl
  canlı doğrulama + stop_server — uçtan uca ajan yapımı, dogrulama=True
- **Full-stack (AJANLAR, 2026-07-16)**: backend + fetch'li frontend + testler; çift
  sunucu aynı anda ayakta, frontend backend'den değeri okudu (screenshot kanıtlı)

## Mekanik korumalar (kaza analizlerinden doğdu)

1. İzole görev klasörleri (eski dosyalar yeni göreve sızmaz)
2. Kanıt şartı: Validator araç çalıştırmadan karar veremez (2 denemede hata)
3. Tekrar kilidi: aynı araç+girdi 3. kez bloklanır (write/edit sıfırlar)
4. Debelenme detektörü: dosya yazmadan 5 ardışık run_shell → uyarı
5. Validator yazma kısıtı: mevcut dosyaya write/edit + yıkıcı kabuk (del/rm/>) engelli
6. Şema uyarısı: bilinmeyen araç parametresi nota çevrilir
7. Sunucu sızıntı önleme: görev sonunda (hata olsa da) tüm arka plan süreçleri kapanır
8. Tur sınırı 35 + validator işaret unutursa netleştirme turu
9. Git: görev klasörü kendi reposunu kurar (üst repoya commit atamaz)
10. check_page dev-server koruması: Vite/Next projesi `file://` ile doğrulanamaz —
    araç reddeder, canlı URL akışını (start_server → http://localhost) tarif eder

## KALDIĞIMIZ YER — sıradaki adımlar (öncelik sırasıyla)

1. ~~check_page'in Vite açığı~~ **KAPATILDI (2026-07-16):** dev-server projesinde
   (yakın package.json'da "dev"/vite/next/react-scripts) veya kökten mutlak ES modülü
   yüklerken check_page'e dosya yolu verilirse mekanik red + doğru akış mesajı
   (start_server → http://localhost:<port>). Validator promptu da güncellendi;
   6 yeni tarayıcısız test.
2. ~~Ajanların full-stack sınavı~~ **GEÇİLDİ (2026-07-16):** Ajanlar backend görevini
   (FastAPI + pytest + canlı uvicorn + curl doğrulaması) ve ardından FULL-STACK görevini
   (backend + fetch'li frontend + testler + çift sunuculu canlı doğrulama) uçtan uca
   kendi başına tamamladı — dogrulama=True, 3/3 pytest, canlı screenshot kanıtı
   (frontend backend'den geleni gösterdi). Sınavlardan çıkan korumalar: run_shell
   arka plan başlatıcı reddi (pipe kilidi), örnekli start_server hatası, debelenme
   detektörünün start_server'ı sayması. Not: Codegen bazen işi yarım bırakıp
   Validator'a devrediyor (rol kayması — Validator yeni dosya yazarak telafi etti).
3. **Codegen'i güçlü kod modeline al:** Nemotron çalışıyor ama savurgan/dalgın
   (vite.config unutma, rol kayması, port sapması). NIM'de Qwen2.5-Coder benzeri
   modeli tutarlılık testinden geçirip `FCC_MODEL_CODEGEN`'e ata → kalite + verim.
4. Faz 5 kalanları: görev kuyruğu, Docker sandbox'ı varsayılan yapmak, model karşılaştırma raporu.
5. Faz 6 (planlandı, başlanmadı): API bağlama yeteneği — sır yönetimi (.env enjeksiyonu),
   pip/npm bağımlılık politikası, Docker'da seçmeli ağ.


## Bilinen kısıtlar / notlar

- Nemotron: Reviewer çıktısında dil karışması olabilir; karmaşık çok-adımlı işlerde
  erken pes etme veya debelenme görülebilir (korumalar hafifletiyor, çözüm: madde 2).
- Vite önizleme "Canlı Önizle" ile açılır (statik `/onizle` Vite için boş — derleme gerekir);
  tarayıcı ilk bozuk hali önbelleğe aldıysa **Ctrl+Shift+R**.
- Proxy'de `ENABLE_MODEL_THINKING=false` (token deneyi; kalite düşerse admin'den geri aç).
- Docker imajı `python:3.12-slim` — node yok; UI/Vite görevlerinde Docker anahtarı kapalı olmalı.
