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
- **NVIDIA NIM kullanılamıyor:** build.nvidia.com kayıtta TR telefon numarası doğrulamıyor;
  anahtar alınamadı. Proxy'nin varsayılan `MODEL` rotası hâlâ NIM'i gösterdiği için istekte
  model her zaman açıkça belirtilmeli (veya admin panelden MODEL, gemini rotasına çevrilmeli).
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

- [ ] Orkestratör: Planner → Codegen → Test/Validator → Debugger → Reviewer akışı
- [ ] 4 ajan tanımı ve sistem promptları (Planner, Codegen, Reviewer, Debugger, Test/Validator)
- [ ] Dosya bazlı state yönetimi (oturumlar arası devam edebilme)
- [ ] Model routing (ajan başına farklı model seçimi)
- [ ] Uçtan uca döngü testi (örnek görev: küçük bir CLI aracı üretimi)

## Faz 3 — UI ve İndeksleme

- [ ] Next.js UI
- [ ] ui-ux-pro-max design tool entegrasyonu
- [ ] Embedding tabanlı repo indexleme (bağlam seçimi için)
- [ ] UI ↔ orkestratör API entegrasyonu
