"""Faz 2 — Dosya bazlı oturum state'i.

Orkestratör her aşamadan sonra state'i JSON olarak diske yazar; böylece
kesilen bir görev sonraki oturumda kaldığı aşamadan sürdürülebilir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjeState:
    """Büyük hedefin alt görev zinciri (Faz 4).

    alt_gorevler öğeleri: {"id": int, "gorev": str, "kabul": str,
    "durum": "bekliyor" | "basarili" | "basarisiz", "ozet": str}
    """

    hedef: str
    alt_gorevler: list[dict] = field(default_factory=list)

    def kaydet(self, yol: Path) -> None:
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text(
            json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def yukle(cls, yol: Path) -> "ProjeState | None":
        if not yol.is_file():
            return None
        try:
            veri = json.loads(yol.read_text(encoding="utf-8"))
            return cls(**veri)
        except (json.JSONDecodeError, TypeError):
            return None


@dataclass
class OturumState:
    gorev: str
    tamamlanan: list[str] = field(default_factory=list)  # biten aşama adları, sırayla
    ciktilar: dict[str, str] = field(default_factory=dict)  # aşama adı → ajan çıktısı
    debug_turu: int = 0  # kaç debugger turu harcandı

    def asama_bitti(self, ad: str, cikti: str) -> None:
        if ad not in self.tamamlanan:
            self.tamamlanan.append(ad)
        self.ciktilar[ad] = cikti

    def kaydet(self, yol: Path) -> None:
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text(
            json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def yukle(cls, yol: Path) -> "OturumState | None":
        """State dosyası varsa yükler; yoksa veya bozuksa None döner."""
        if not yol.is_file():
            return None
        try:
            veri = json.loads(yol.read_text(encoding="utf-8"))
            return cls(**veri)
        except (json.JSONDecodeError, TypeError):
            return None
