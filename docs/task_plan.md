# Görev Planı — Agentic Kod Üretim Ürünü

## Hedef

[free-claude-code](https://github.com/Alishahryar1/free-claude-code) proxy'sini LLM erişim katmanı
olarak kullanan agentic bir kod üretim ürünü inşa etmek. Proxy, Anthropic Messages API formatını
taklit ederek istekleri NVIDIA NIM / OpenRouter gibi sağlayıcılara yönlendirir ve
`http://localhost:8082/v1/messages` adresinde çalışır. Sistemin kendi bileşenleri:
orkestratör, Tool Executor ve 4 ajan (Planner, Codegen, Reviewer, Debugger, Test/Validator).

---

## Faz 0 — Altyapı Doğrulama (bu oturum)

Proxy bağlantısının ve tool-use davranışının güvenilirliğini doğrula. Agentic döngü tamamen
tool çağrılarına dayandığı için, proxy'nin arkasındaki modellerin tool-use şemasına tutarlı
uyup uymadığını ölçmeden ileri fazlara geçilmez.

- [x] Proje iskeleti: klasörler, git init, .gitignore, pyproject.toml (uv; httpx + pytest)
- [x] docs/task_plan.md oluşturuldu
- [x] tests/test_tool_use_consistency.py yazıldı (10 tekrarlı tool-use tutarlılık testi)
- [x] README.md'ye çalıştırma talimatı eklendi
- [x] Proxy (fcc-server) ayrı terminalde başlatıldı
- [x] Tutarlılık testi çalıştırıldı ve sonuç değerlendirildi — **10/10 geçerli tool_use** (gemini/gemini-2.5-flash)
- [x] Karar: birincil model **Gemini 2.5 Flash** (tool-use tutarlılığı doğrulandı)

### Faz 0 bulguları (2026-07-06)

- **Gemini 2.5 Flash: 10/10 geçerli tool_use.** İstekte model `gemini/gemini-2.5-flash`
  biçiminde verilince proxy doğrudan Gemini'ye yönlendiriyor (provider/model söz dizimi).
- ~~NVIDIA NIM kullanılamıyor~~ **Güncelleme (2026-07-14):** kullanıcı `nvapi-` anahtarı
  alabildi. Nemotron-3-Super tool-use testi **10/10**; varsayılan `MODEL` rotası artık
  çalışıyor ve NIM, geniş kotasıyla birincil sağlayıcı. Gemini/Groq yedek.
- **OpenRouter ücretsiz katman bu iş için uygun değil:** kredisiz hesapta günde ~50 istek;
  test sırasında kota tükendi (kalıcı 429). Agentic döngü için ancak kredi yüklenirse anlamlı.
- Test scripti `FCC_TEST_MODEL`, `FCC_TEST_REPEAT`, `FCC_TEST_DELAY` ve `ANTHROPIC_AUTH_TOKEN`
  ortam değişkenleriyle ayarlanabiliyor; sağlayıcı hatalarını (429 vb.) model hatalarından
  ayırıyor ve otomatik yeniden deniyor.

## Faz 1 — Tool Executor

Ajanların dosya sistemi ve kabukla güvenli etkileşimini sağlayan katman.

- [x] `read_file` / `write_file` / `run_shell` araçları (`orchestrator/tool_executor.py`)
- [x] Path doğrulama (workspace dışına çıkışı engelle: path traversal koruması)
- [x] Yazma işlemlerinde diff üretimi (değişikliklerin izlenebilirliği)
- [x] Docker sandbox içinde shell çalıştırma — `DockerShellRunner` (ağa kapalı konteyner,
      workspace `/workspace` olarak bağlanır, imaj: python:3.12-slim); 6 entegrasyon testi
      geçti (`tests/test_docker_sandbox.py`, Docker kapalıysa otomatik atlanır)
- [x] Tool Executor birim testleri (23 test: path kaçışları, diff, zaman aşımı, dispatcher)

## Faz 2 — Agentic Döngü + Ajanlar

Orkestratörün yönettiği çok-ajanlı üretim döngüsü.

- [x] Orkestratör: Planner → Codegen → Test/Validator → Debugger → Reviewer akışı
      (`orchestrator/loop.py`; debugger↔validator döngüsü en çok 3 tur)
- [x] 5 ajan tanımı ve sistem promptları (`orchestrator/agents.py`; ajan başına araç izni)
- [x] Dosya bazlı state yönetimi (`orchestrator/state.py`; `.state/oturum.json`, `--devam`
      ile kaldığı yerden sürer)
- [x] Model routing (ajan başına `FCC_MODEL_<AJAN>`, genel `FCC_MODEL`; varsayılan
      gemini/gemini-2.5-flash)
- [x] Orkestratör birim testleri (11 test, sahte LLM istemcisiyle ağsız)
- [x] Uçtan uca döngü testi — **temiz tam tur başarılı (2026-07-14, Gemini 2.5 Flash):**
      doğrulama ilk denemede geçti (0 debug turu), validator dosyalara dokunmadı,
      6/6 pytest + elle doğrulama; reviewer isabetli eksik-test önerileri raporladı.
      (Düzeltme notu: koşu sırada ajan varsayılanı kodda gemini'ye sabitlenmişti; artık
      varsayılan, proxy'nin MODEL rotasına — yani NIM'e — gidiyor.)

### Faz 2 iyileştirme listesi (2026-07-08 canlı koşu bulguları)

- [x] **Rol sınırlarını kodda zorla:** validator'ın write_file'ı yalnızca var olmayan
      dosyalara izinli (`AjanTanimi.mevcut_dosyayi_degistiremez`, orkestratörde mekanik
      kontrol; ihlalde modele is_error'lı açıklama döner)
- [x] **Token verimliliği:** son tur hariç geçmişteki tool_result içerikleri 400 karaktere
      kırpılıyor (`_gecmisi_kirp`); en güncel araç çıktısı tam kalır
- [ ] Model kalite notu: Llama 3.3 70B kod kalitesi zayıf (unicode-kaçışlı Türkçe metin,
      yazım hatası, exec tabanlı kırılgan test). Codegen/Debugger için Gemini tercih;
      Llama ancak Planner/Reviewer gibi hafif roller için düşünülmeli.

## Faz 3 — UI ve İndeksleme

- [x] UI ↔ orkestratör API entegrasyonu (`orchestrator/api.py`: FastAPI; POST /api/gorev,
      GET /api/durum canlı log yoklama, GET /api/saglik; 5 test)
- [x] Next.js UI (`ui/`: görev formu, model seçimi, Docker anahtarı, ajan renkli canlı
      log akışı, doğrulama sonucu + plan + reviewer raporu; koyu tema)
- [x] ui-ux-pro-max design tool entegrasyonu — tasarım sistemi üretildi (OLED koyu tema,
      slate paleti, Fira Code/Sans, yoğun panel düzeni) ve arayüze uygulandı; SVG ikon
      seti, görünür odak halkaları, prefers-reduced-motion desteği
- [x] Repo indexleme (`orchestrator/indeks.py` + `search_files` aracı): TF-IDF varsayılan
      (kotasız), `FCC_EMBEDDING=gemini` ile embedding tabanlı
- [x] UI üzerinden uçtan uca gerçek görev — API yoluyla canlı doğrulandı (2026-07-14,
      dogrulama_gecti=True); UI'ye proje modu anahtarı + alt görev durum listesi eklendi

## Faz 4 — Görev Ayrıştırma: Büyük Hedef Desteği

Tek döngü birkaç dosyalık görevleri götürüyor; "e-ticaret sitesi" ölçeğindeki hedefler için
üst katman: hedefi alt görev zincirine bölen Decomposer + proje düzeyinde state + alt
görevler arası bağlam taşıma. Önkoşullar: Faz 2 iyileştirme listesi (token verimliliği,
rol kısıtları) ve yeterli kota.

- [x] `list_files` aracı (Tool Executor'a eklendi; tüm ajanlarda izinli, üretilen
      klasörleri — .git, node_modules, __pycache__ vb. — gizler)
- [x] Üst-Planner (Decomposer) ajanı: hedef → JSON alt görev listesi
      (`orchestrator/proje.py`; çit/önsöz toleranslı JSON ayıklama)
- [x] Proje state'i (`.state/proje.json`): alt görev durumları, `--devam` ile başarılılar
      atlanır; başarısız alt görev zinciri durdurur
- [x] Bağlam taşıma: biten alt görevin codegen özeti (500 karakter) + güncel dosya
      listesi sonraki alt görevin girdisine eklenir
- [x] CLI: `uv run python -m orchestrator --proje "büyük hedef"`
- [x] **İlk gerçek --proje koşusu başarılı (2026-07-14, NIM):** "not defteri uygulaması"
      hedefi 4 alt göreve bölündü, 4/4 tamamlandı — notlar.py + notdefteri.py +
      17 pytest testi (hepsi geçiyor, CLI elle doğrulandı). Kesinti sonrası --devam,
      netleştirme turu ve validator yazma engeli canlıda çalıştı.
- [ ] Entegrasyon doğrulaması: tüm alt görevler bitince final Validator turu
- [x] UI: alt görev listesi görünümü (proje modu anahtarı + durum ikonlu liste);
      insan onay noktası (devam/düzelt) hâlâ açık
- [ ] Sertleştirme notu: validator run_shell üzerinden dosya silebiliyor (`del notlar.json`
      görüldü) — yazma kısıtının kabuk yan-kanalı da düşünülmeli
