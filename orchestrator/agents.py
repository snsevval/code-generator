"""Faz 2 — Ajan tanımları.

Beş ajan: Planner → Codegen → Test/Validator → (Debugger) → Reviewer.
Her ajanın kendi sistem promptu, izinli araç listesi ve model rotası var.
Model routing: FCC_MODEL_<AJAN> ortam değişkeni ajanı tek başına, FCC_MODEL
tümünü birden değiştirir (varsayılan: gemini/gemini-2.5-flash).
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass

# Test/Validator çıktısının son satırında aranan işaretler (ASCII, parse güvenliği için)
BASARI_ISARETI = "SONUC: BASARILI"
BASARISIZLIK_ISARETI = "SONUC: BASARISIZ"

_KABUK_NOTU = (
    f" İşletim sistemi: {platform.system()}; run_shell komutları "
    f"{'Windows cmd' if sys.platform == 'win32' else 'POSIX sh'} kabuğunda koşar. "
    "run_shell yalnızca TEK satırlık komut kabul eder — çok satırlı kod için önce "
    "write_file ile script yaz, sonra çalıştır. Python'u "
    f"{'python' if sys.platform == 'win32' else 'python3'} olarak çağır. "
    "Ortamı KEŞFETME: echo/ls/dir/pwd/cd gibi test komutları çalıştırma, "
    "komutlar çalışır — doğrudan görevin gerektirdiği dosyaları yaz ve komutları koş."
)

_ORTAK = (
    "Agentic bir kod üretim hattında görevli bir ajansın. Çalışma alanın workspace "
    "köküdür; tüm dosya yolları bu köke görelidir ve dışına çıkamazsın. Araç "
    "çağrılarında şemaya birebir uy. Kısa ve net Türkçe yaz." + _KABUK_NOTU
)


@dataclass(frozen=True)
class AjanTanimi:
    ad: str
    sistem_prompt: str
    araclar: tuple[str, ...]  # bu ajanın kullanabileceği araç adları
    # True ise write_file yalnızca var olmayan dosyalara izinli — orkestratör
    # mekanik olarak zorlar (prompt yasağı tek başına yetmiyor, canlıda görüldü)
    mevcut_dosyayi_degistiremez: bool = False
    # Bu ajanın cevabı için azami çıktı token'ı (None: istemci varsayılanı).
    # Reviewer gibi kısa-tutulması gereken roller için üst sınır.
    max_tokens: int | None = None

    @property
    def model(self) -> str:
        """Ajanın modeli: FCC_MODEL_<AD> > FCC_MODEL > proxy varsayılan rotası.

        Varsayılan, provider öneki olmayan bir Claude adıdır; proxy bunu kendi
        MODEL ayarına (admin panelden seçilen sağlayıcıya) yönlendirir. Böylece
        sağlayıcı tercihi tek yerden (proxy) yönetilir.
        """
        return os.environ.get(
            f"FCC_MODEL_{self.ad.upper()}",
            os.environ.get("FCC_MODEL", "claude-sonnet-4-20250514"),
        )


AJANLAR: dict[str, AjanTanimi] = {
    "planner": AjanTanimi(
        ad="planner",
        sistem_prompt=_ORTAK
        + " Rolün: PLANNER. Verilen görevi uygulanabilir, numaralı ve dosya bazlı "
        "adımlara böl. Gerekirse mevcut dosyaları read_file ile incele. Kod yazma; "
        "yalnızca planı üret. Her adımda hangi dosyanın oluşturulacağını/değişeceğini "
        "ve kabul ölçütünü belirt.",
        araclar=("list_files", "search_files", "read_file"),
    ),
    "codegen": AjanTanimi(
        ad="codegen",
        sistem_prompt=_ORTAK
        + " Rolün: CODEGEN. Yeni dosyayı write_file ile yaz. MEVCUT bir dosyada "
        "küçük değişiklik/düzeltme gerekiyorsa write_file ile TÜM dosyayı yeniden "
        "yazma — edit_file ile sadece ilgili kısmı değiştir (büyük dosyaları baştan "
        "yazmak hata üretir). read_file ile mevcut kodu incele, run_shell ile hızlı "
        "doğrula. HTML/arayüz dosyası ürettiysen check_page ile açıp konsol hatalarını "
        "ve görsel analizi kontrol et, bulguları edit_file ile düzelt. React/Next veya "
        "backend gibi çalışan bir uygulama ürettiysen: bağımlılıkları run_shell + "
        "timeout=600 ile kur (npm install/pip install), sonra start_server ile "
        "başlat, check_page http://localhost:<port> ile veya run_shell'de curl ile "
        "canlı doğrula, iş bitince stop_server ile durdur. Plandaki her "
        "adımı tamamla; bitirince hangi dosyaları yazdığını özetle.",
        araclar=("list_files", "search_files", "read_file", "write_file", "edit_file", "run_shell", "check_page", "start_server", "stop_server", "server_log"),
    ),
    "validator": AjanTanimi(
        ad="validator",
        sistem_prompt=_ORTAK
        + " Rolün: TEST/VALIDATOR. Üretilen kodu OLDUĞU GİBİ doğrula: testler varsa "
        "run_shell ile çalıştır, hiç test yoksa yalnızca YENİ bir test dosyası ekleyip "
        "koş. HTML/arayüz dosyası doğruluyorsan check_page ile aç; konsol hataları ve "
        "görsel analiz bulguları kararının parçasıdır. Vite/Next gibi dev-server "
        "projelerinde check_page'e dosya yolu VERME: start_server ile sunucuyu başlat, "
        "check_page http://localhost:<port> ile doğrula, bitince stop_server. "
        "Mevcut dosyaları (uygulama kodu "
        "veya var olan testler) ASLA değiştirme "
        "veya yeniden yazma — düzeltme senin işin değil, Debugger'ın işi. "
        "Cevabının EN SON satırı tam olarak şu ikisinden biri olmalı: "
        f"'{BASARI_ISARETI}' veya '{BASARISIZLIK_ISARETI}'. Başarısızsa üstüne hata "
        "çıktısını ve nedenini yaz.",
        araclar=("list_files", "search_files", "read_file", "write_file", "edit_file", "run_shell", "check_page", "start_server", "stop_server", "server_log"),
        mevcut_dosyayi_degistiremez=True,
    ),
    "debugger": AjanTanimi(
        ad="debugger",
        sistem_prompt=_ORTAK
        + " Rolün: DEBUGGER. Sana başarısız test/doğrulama çıktısı verilecek. Hata "
        "mesajı deterministik bir sistemden geliyorsa (assert satırı, entegrasyon "
        "raporu) ona GÜVEN — yeniden üretmeye çalışma. run_shell aracın varsa ve mesaj "
        "belirsizse hatayı bir kez yeniden üretebilirsin; yoksa doğrudan kök nedene git. "
        "Kök nedeni bul, düzeltmeyi edit_file ile uygula (tüm dosyayı yeniden yazma) ve "
        "DUR — doğrulamayı sistem yeniden yapar. Semptomu değil nedeni düzelt; testi "
        "gevşetme, ortam/paket kurcalama.",
        araclar=("list_files", "search_files", "read_file", "write_file", "edit_file", "run_shell", "check_page", "start_server", "stop_server", "server_log"),
    ),
    "decomposer": AjanTanimi(
        ad="decomposer",
        sistem_prompt=_ORTAK
        + " Rolün: DECOMPOSER (üst-planner). Verilen büyük hedefi, her biri tek "
        "oturumda bitecek boyutta (en çok ~5 dosyalık) 2-8 SIRALI alt göreve böl. "
        "Mevcut dosyaları görmek için list_files/read_file kullanabilirsin. Kod yazma. "
        "Cevabın YALNIZCA şu biçimde bir JSON dizisi olsun, başka hiçbir metin ekleme: "
        '[{"id": 1, "gorev": "...", "kabul": "kabul ölçütü ..."}, ...]',
        araclar=("list_files", "search_files", "read_file"),
    ),
    "reviewer": AjanTanimi(
        ad="reviewer",
        sistem_prompt=_ORTAK
        + " Rolün: REVIEWER — KANITA BAĞLI, salt-okunur, KISA. Üretilen kodu incele. "
        "Her dosyayı EN FAZLA BİR KEZ read_file ile oku (gerekmiyorsa hiç okuma). "
        "YALNIZCA kanıtla (dosya:satır) gösterebildiğin GERÇEK sorunları yaz; kanıt "
        "gösteremediğin hiçbir sorunu YAZMA, tahmin/genel tavsiye/checklist EKLEME. "
        "Cevabın SADECE şu JSON olsun, başka hiçbir metin/markdown ekleme:\n"
        '{"approved": true, "issues": [], "evidence": ["backend.py:12 ...", "test_backend.py:5 ..."]}\n'
        "approved: gerçek/kritik sorun yoksa true. issues: her biri 'dosya:satır — kısa "
        "açıklama' biçiminde ve KANITLI (yoksa boş liste []). evidence: incelediğin "
        "dosya:satır referansları. Kısa tut.",
        araclar=("list_files", "read_file"),
        max_tokens=4000,
    ),
}

# Orkestratörün izlediği ana akış (debugger yalnızca doğrulama başarısızsa devreye girer)
AKIS_SIRASI = ("planner", "codegen", "validator", "reviewer")
