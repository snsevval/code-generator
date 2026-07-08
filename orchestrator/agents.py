"""Faz 2 — Ajan tanımları.

Beş ajan: Planner → Codegen → Test/Validator → (Debugger) → Reviewer.
Her ajanın kendi sistem promptu, izinli araç listesi ve model rotası var.
Model routing: FCC_MODEL_<AJAN> ortam değişkeni ajanı tek başına, FCC_MODEL
tümünü birden değiştirir (varsayılan: gemini/gemini-2.5-flash).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Test/Validator çıktısının son satırında aranan işaretler (ASCII, parse güvenliği için)
BASARI_ISARETI = "SONUC: BASARILI"
BASARISIZLIK_ISARETI = "SONUC: BASARISIZ"

_ORTAK = (
    "Agentic bir kod üretim hattında görevli bir ajansın. Çalışma alanın workspace "
    "köküdür; tüm dosya yolları bu köke görelidir ve dışına çıkamazsın. Araç "
    "çağrılarında şemaya birebir uy. Kısa ve net Türkçe yaz."
)


@dataclass(frozen=True)
class AjanTanimi:
    ad: str
    sistem_prompt: str
    araclar: tuple[str, ...]  # bu ajanın kullanabileceği araç adları

    @property
    def model(self) -> str:
        """Ajanın modeli: FCC_MODEL_<AD> > FCC_MODEL > varsayılan."""
        return os.environ.get(
            f"FCC_MODEL_{self.ad.upper()}",
            os.environ.get("FCC_MODEL", "gemini/gemini-2.5-flash"),
        )


AJANLAR: dict[str, AjanTanimi] = {
    "planner": AjanTanimi(
        ad="planner",
        sistem_prompt=_ORTAK
        + " Rolün: PLANNER. Verilen görevi uygulanabilir, numaralı ve dosya bazlı "
        "adımlara böl. Gerekirse mevcut dosyaları read_file ile incele. Kod yazma; "
        "yalnızca planı üret. Her adımda hangi dosyanın oluşturulacağını/değişeceğini "
        "ve kabul ölçütünü belirt.",
        araclar=("read_file",),
    ),
    "codegen": AjanTanimi(
        ad="codegen",
        sistem_prompt=_ORTAK
        + " Rolün: CODEGEN. Sana verilen planı uygula: dosyaları write_file ile yaz, "
        "gerekirse read_file ile mevcut kodu incele, hızlı doğrulamalar için run_shell "
        "kullanabilirsin. Plandaki her adımı tamamla; bitirince hangi dosyaları "
        "yazdığını özetle.",
        araclar=("read_file", "write_file", "run_shell"),
    ),
    "validator": AjanTanimi(
        ad="validator",
        sistem_prompt=_ORTAK
        + " Rolün: TEST/VALIDATOR. Üretilen kodu OLDUĞU GİBİ doğrula: testler varsa "
        "run_shell ile çalıştır, hiç test yoksa yalnızca YENİ bir test dosyası ekleyip "
        "koş. Mevcut dosyaları (uygulama kodu veya var olan testler) ASLA değiştirme "
        "veya yeniden yazma — düzeltme senin işin değil, Debugger'ın işi. "
        "Cevabının EN SON satırı tam olarak şu ikisinden biri olmalı: "
        f"'{BASARI_ISARETI}' veya '{BASARISIZLIK_ISARETI}'. Başarısızsa üstüne hata "
        "çıktısını ve nedenini yaz.",
        araclar=("read_file", "write_file", "run_shell"),
    ),
    "debugger": AjanTanimi(
        ad="debugger",
        sistem_prompt=_ORTAK
        + " Rolün: DEBUGGER. Sana başarısız test/doğrulama çıktısı verilecek. Kök "
        "nedeni bul, ilgili dosyaları read_file ile incele, düzeltmeyi write_file ile "
        "uygula ve run_shell ile düzeltmenin tuttuğunu göster. Semptomu değil nedeni "
        "düzelt.",
        araclar=("read_file", "write_file", "run_shell"),
    ),
    "reviewer": AjanTanimi(
        ad="reviewer",
        sistem_prompt=_ORTAK
        + " Rolün: REVIEWER. Üretilen kodu read_file ile incele ve kısa bir inceleme "
        "raporu yaz: doğruluk riskleri, basitleştirme fırsatları, eksik testler. "
        "Dosya değiştirme; yalnızca raporla.",
        araclar=("read_file",),
    ),
}

# Orkestratörün izlediği ana akış (debugger yalnızca doğrulama başarısızsa devreye girer)
AKIS_SIRASI = ("planner", "codegen", "validator", "reviewer")
