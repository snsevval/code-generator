"""Faz 3 — Repo indeksi: sorguya göre ilgili dosyaları bulur.

Ajanların büyük/mevcut projelerde doğru dosyaları seçebilmesi için
`search_files` aracının arkasındaki katman. İki arka uç:

- **TF-IDF (varsayılan):** tamamen yerel, kotasız; tanımlayıcı adlarını
  (camelCase/snake_case) parçalayarak kod aramasına uygun skorlar üretir.
- **Gemini embedding (opsiyonel):** `FCC_EMBEDDING=gemini` ve `GEMINI_API_KEY`
  ayarlıysa anlamsal arama; API kotası harcar.

Workspace küçük tutulduğundan indeks her sorguda yeniden kurulur (ms düzeyi);
kalıcı önbellek gerekirse Faz 4 sertleştirmesinde eklenir.
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path

import httpx

from orchestrator.tool_executor import GIZLENEN_KLASORLER

# Yalnızca metin dosyaları indekslenir
INDEKSLENEN_UZANTILAR = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".toml",
    ".yaml", ".yml", ".html", ".css", ".sql", ".sh", ".ps1", ".cfg", ".ini",
}
MAX_DOSYA_BOYUTU = 128 * 1024  # bayt; daha büyük dosyaların başı okunur
_TANIMLAYICI = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL_BOLME = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _parcala(metin: str) -> list[str]:
    """Metni arama birimlerine böler: tanımlayıcılar + camelCase/snake_case parçaları."""
    parcalar: list[str] = []
    for tanimlayici in _TANIMLAYICI.findall(metin):
        parcalar.append(tanimlayici.lower())
        alt = [p for golge in tanimlayici.split("_") for p in _CAMEL_BOLME.split(golge) if p]
        if len(alt) > 1:
            parcalar.extend(p.lower() for p in alt)
    return parcalar


class TfIdfVektorleyici:
    """Kotasız yerel arka uç: seyrek TF-IDF vektörleri + kosinüs benzerliği."""

    def vektorle(self, metinler: list[str], sorgu: str) -> list[float]:
        """Her metnin sorguya benzerlik skorunu döndürür."""
        belgeler = [_parcala(m) for m in metinler]
        sorgu_parcalari = _parcala(sorgu)
        n = len(belgeler)
        if n == 0:
            return []

        # idf: sorgu ve belgelerin ortak sözlüğü üzerinden
        belge_frekansi: dict[str, int] = {}
        for parcalar in belgeler:
            for kelime in set(parcalar):
                belge_frekansi[kelime] = belge_frekansi.get(kelime, 0) + 1

        def tfidf(parcalar: list[str]) -> dict[str, float]:
            vektor: dict[str, float] = {}
            for kelime in parcalar:
                vektor[kelime] = vektor.get(kelime, 0.0) + 1.0
            for kelime in vektor:
                idf = math.log((1 + n) / (1 + belge_frekansi.get(kelime, 0))) + 1.0
                vektor[kelime] *= idf
            return vektor

        def kosinus(a: dict[str, float], b: dict[str, float]) -> float:
            if not a or not b:
                return 0.0
            pay = sum(deger * b.get(kelime, 0.0) for kelime, deger in a.items())
            norm_a = math.sqrt(sum(d * d for d in a.values()))
            norm_b = math.sqrt(sum(d * d for d in b.values()))
            return pay / (norm_a * norm_b) if pay else 0.0

        sorgu_vektoru = tfidf(sorgu_parcalari)
        return [kosinus(sorgu_vektoru, tfidf(b)) for b in belgeler]


class GeminiVektorleyici:
    """Gemini embedding arka ucu (FCC_EMBEDDING=gemini ile etkin; kota harcar)."""

    URL = (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-embedding-001:batchEmbedContents"
    )

    def __init__(self, api_key: str | None = None):
        self._anahtar = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self._anahtar:
            raise ValueError("GEMINI_API_KEY ayarlı değil (FCC_EMBEDDING=gemini için gerekli)")

    def _embed(self, metinler: list[str], gorev_tipi: str) -> list[list[float]]:
        yanit = httpx.post(
            self.URL,
            headers={"x-goog-api-key": self._anahtar},
            json={
                "requests": [
                    {
                        "model": "models/gemini-embedding-001",
                        "content": {"parts": [{"text": m[:8000]}]},
                        "taskType": gorev_tipi,
                    }
                    for m in metinler
                ]
            },
            timeout=60.0,
        )
        yanit.raise_for_status()
        return [e["values"] for e in yanit.json()["embeddings"]]

    def vektorle(self, metinler: list[str], sorgu: str) -> list[float]:
        if not metinler:
            return []
        belgeler = self._embed(metinler, "RETRIEVAL_DOCUMENT")
        sorgu_v = self._embed([sorgu], "RETRIEVAL_QUERY")[0]

        def kosinus(a: list[float], b: list[float]) -> float:
            pay = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            return pay / (na * nb) if na and nb else 0.0

        return [kosinus(sorgu_v, b) for b in belgeler]


def _vektorleyici_sec():
    if os.environ.get("FCC_EMBEDDING", "").lower() == "gemini":
        return GeminiVektorleyici()
    return TfIdfVektorleyici()


class RepoIndeksi:
    def __init__(self, workspace: Path | str, vektorleyici=None):
        self.workspace = Path(workspace).resolve()
        self._vektorleyici = vektorleyici or _vektorleyici_sec()

    def _dosyalari_topla(self) -> list[tuple[str, str]]:
        """(göreli yol, içerik) çiftleri; gizlenen klasörler ve ikili dosyalar hariç."""
        sonuc: list[tuple[str, str]] = []
        for kok, klasorler, dosyalar in os.walk(self.workspace):
            klasorler[:] = sorted(k for k in klasorler if k not in GIZLENEN_KLASORLER)
            for ad in sorted(dosyalar):
                p = Path(kok) / ad
                if p.suffix.lower() not in INDEKSLENEN_UZANTILAR:
                    continue
                icerik = p.read_bytes()[:MAX_DOSYA_BOYUTU].decode("utf-8", errors="replace")
                gorel = p.relative_to(self.workspace).as_posix()
                # Dosya adı da aranabilir olsun diye içeriğe eklenir
                sonuc.append((gorel, f"{gorel}\n{icerik}"))
        return sonuc

    def sorgula(self, sorgu: str, k: int = 5) -> list[dict]:
        """Sorguya en benzeyen k dosyayı skor ve örnek satırla döndürür."""
        dosyalar = self._dosyalari_topla()
        if not dosyalar:
            return []
        skorlar = self._vektorleyici.vektorle([icerik for _, icerik in dosyalar], sorgu)
        sirali = sorted(zip(dosyalar, skorlar), key=lambda c: c[1], reverse=True)

        sonuc = []
        sorgu_parcalari = set(_parcala(sorgu))
        for (yol, icerik), skor in sirali[:k]:
            if skor <= 0:
                continue
            ornek = ""
            for satir in icerik.splitlines()[1:]:  # ilk satır dosya adı
                if sorgu_parcalari & set(_parcala(satir)):
                    ornek = satir.strip()[:120]
                    break
            sonuc.append({"dosya": yol, "skor": round(float(skor), 3), "ornek": ornek})
        return sonuc

    def sorgula_metin(self, sorgu: str, k: int = 5) -> str:
        """search_files aracının modele dönen metin çıktısı."""
        sonuclar = self.sorgula(sorgu, k)
        if not sonuclar:
            return "Eşleşen dosya bulunamadı."
        satirlar = [
            f"{s['dosya']} (skor {s['skor']})" + (f" — {s['ornek']}" if s["ornek"] else "")
            for s in sonuclar
        ]
        return "\n".join(satirlar)
