"""Faz 3 — UI backend API'si.

Next.js arayüzünün orkestratörle konuştuğu ince HTTP katmanı:

- POST /api/gorev  → görevi arka plan iş parçacığında başlatır (aynı anda tek görev)
- GET  /api/durum  → canlı log satırları + çalışma durumu + sonuç (UI bunu yoklar)
- GET  /api/saglik → API ve proxy'nin ayakta olup olmadığı

Çalıştırma:
    uv run uvicorn orchestrator.api:app --port 8090
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import mimetypes

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from orchestrator.calisma_alani import gorev_klasoru_sec
from orchestrator.llm_client import VARSAYILAN_PROXY_URL
from orchestrator.loop import Orkestrator
from orchestrator.proje import ProjeOrkestratoru
from orchestrator.tasarim import gorevi_zenginlestir
from orchestrator.tool_executor import (
    GIZLENEN_KLASORLER,
    DockerShellRunner,
    ToolExecutor,
)

app = FastAPI(title="code-generator API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev sunucusu
    allow_methods=["*"],
    allow_headers=["*"],
)


class GorevIstegi(BaseModel):
    gorev: str
    model: str | None = None  # örn. "groq/llama-3.3-70b-versatile"; boşsa varsayılan
    docker: bool = False
    devam: bool = False
    proje: bool = False  # True: hedef alt görevlere bölünüp zincir halinde koşulur
    onayli: bool = False  # True: her alt görevden sonra kullanıcı onayı beklenir
    tasarim: bool = False  # True: göreve ui-ux-pro-max tasarım sistemi enjekte edilir


class OnayKarari(BaseModel):
    devam: bool


ONAY_ZAMAN_ASIMI_SN = 3600.0  # onay bu süre içinde gelmezse zincir güvenli tarafta durur


class _Durum:
    """Süreç içi tekil görev durumu (UI'nin yokladığı her şey)."""

    def __init__(self):
        self.kilit = threading.Lock()
        self.calisiyor = False
        self.gorev: str | None = None
        self.log: list[str] = []
        self.hata: str | None = None
        self.sonuc: dict | None = None
        # Onay bekleyen alt görev bilgisi (None: onay beklenmiyor)
        self.onay_bekleyen: dict | None = None
        self.onay_olayi = threading.Event()
        self.onay_karari = False
        # Koşan orkestratörün LLM istemcisi (token sayacı buradan okunur)
        self.istemci = None
        # Görevin izole çalışma klasörü (UI'de gösterilir + dosya servisi kökü)
        self.klasor: str | None = None
        self.klasor_yolu: Path | None = None


DURUM = _Durum()


def _gorev_kos(istek: GorevIstegi) -> None:
    """Arka plan iş parçacığı: görevi koşar, durumu günceller."""
    try:
        if istek.model:
            os.environ["FCC_MODEL"] = istek.model
        taban = Path(os.environ.get("FCC_WORKSPACE", "workspace")).resolve()
        # Görev başına izole klasör: eski görevlerin dosyaları yenisine sızmasın
        ws = gorev_klasoru_sec(taban, devam=istek.devam, proje=istek.proje)
        DURUM.klasor = f"{taban.name}/{ws.name}"
        DURUM.klasor_yolu = ws
        runner = DockerShellRunner(ws) if istek.docker else None
        log = lambda satir: DURUM.log.append(satir)  # noqa: E731
        ork = ORKESTRATOR_FABRIKASI(ws, ToolExecutor(ws, shell_runner=runner), log)
        DURUM.istemci = getattr(ork, "istemci", None)

        gorev_metni = istek.gorev
        if istek.tasarim:
            log("[tasarım] ui-ux-pro-max tasarım sistemi üretiliyor...")
            gorev_metni = TASARIM_ZENGINLESTIRICI(gorev_metni)
            log(
                "[tasarım] tasarım sistemi göreve eklendi."
                if gorev_metni != istek.gorev
                else "[tasarım] tasarım scripti bulunamadı, görev değişmeden sürüyor."
            )
        if istek.proje:
            onay = _onay_bekle if istek.onayli else None
            proje = ProjeOrkestratoru(ws, orkestrator=ork, log=log, onay_callback=onay)
            pstate = proje.hedef_calistir(gorev_metni, devam=istek.devam)
            DURUM.sonuc = {
                "proje": True,
                "alt_gorevler": [
                    {"id": a["id"], "gorev": a["gorev"], "durum": a["durum"]}
                    for a in pstate.alt_gorevler
                ],
                "entegrasyon": pstate.entegrasyon,
                "dogrulama_gecti": (
                    all(a["durum"] == "basarili" for a in pstate.alt_gorevler)
                    and pstate.entegrasyon == "basarili"
                ),
            }
        else:
            state = ork.gorev_calistir(gorev_metni, devam=istek.devam)
            DURUM.sonuc = {
                "proje": False,
                "dogrulama_gecti": state.ciktilar.get("dogrulama_gecti") == "True",
                "debug_turu": state.debug_turu,
                "reviewer": state.ciktilar.get("reviewer", ""),
                "plan": state.ciktilar.get("planner", ""),
            }
    except Exception as e:  # UI'ye okunur hata taşınır
        DURUM.hata = f"{type(e).__name__}: {e}"
    finally:
        DURUM.calisiyor = False


def _onay_bekle(alt: dict) -> bool:
    """Onaylı proje modunda alt görev sonrası kullanıcı kararını bekler.

    UI, /api/durum'dan onay_bekleyen'i görür; kullanıcı /api/onay'a karar
    gönderince zincir sürer. Zaman aşımında güvenli tarafta durulur.
    """
    DURUM.onay_olayi.clear()
    DURUM.onay_karari = False
    DURUM.onay_bekleyen = {"id": alt["id"], "gorev": alt["gorev"]}
    geldi = DURUM.onay_olayi.wait(timeout=ONAY_ZAMAN_ASIMI_SN)
    DURUM.onay_bekleyen = None
    return DURUM.onay_karari if geldi else False


def _varsayilan_fabrika(ws: Path, executor: ToolExecutor, log) -> Orkestrator:
    return Orkestrator(ws, executor=executor, log=log)


# Testlerin sahte orkestratör/zenginleştirici enjekte edebilmesi için modül düzeyinde
ORKESTRATOR_FABRIKASI = _varsayilan_fabrika
TASARIM_ZENGINLESTIRICI = gorevi_zenginlestir


@app.post("/api/gorev")
def gorev_baslat(istek: GorevIstegi):
    if not istek.gorev.strip():
        raise HTTPException(422, "gorev boş olamaz")
    with DURUM.kilit:
        if DURUM.calisiyor:
            raise HTTPException(409, "zaten çalışan bir görev var")
        DURUM.calisiyor = True
        DURUM.gorev = istek.gorev
        DURUM.log = []
        DURUM.hata = None
        DURUM.sonuc = None
    threading.Thread(target=_gorev_kos, args=(istek,), daemon=True).start()
    return {"baslatildi": True, "gorev": istek.gorev}


@app.get("/api/durum")
def durum():
    return {
        "calisiyor": DURUM.calisiyor,
        "gorev": DURUM.gorev,
        "log": DURUM.log,
        "hata": DURUM.hata,
        "sonuc": DURUM.sonuc,
        "onay_bekleyen": DURUM.onay_bekleyen,
        "kullanim": getattr(DURUM.istemci, "kullanim", None),
        "klasor": DURUM.klasor,
    }


@app.post("/api/onay")
def onay_ver(karar: OnayKarari):
    if DURUM.onay_bekleyen is None:
        raise HTTPException(409, "onay bekleyen bir alt görev yok")
    DURUM.onay_karari = karar.devam
    DURUM.onay_olayi.set()
    return {"alindi": True, "devam": karar.devam}


@app.get("/api/dosyalar")
def dosyalar():
    """Aktif görev klasöründeki dosyaları listeler (UI'deki Çıktı Dosyaları)."""
    if DURUM.klasor_yolu is None or not DURUM.klasor_yolu.is_dir():
        return {"dosyalar": []}
    kok = DURUM.klasor_yolu
    liste = []
    for kok_dizin, klasorler, adlar in os.walk(kok):
        klasorler[:] = [
            k for k in klasorler if k not in GIZLENEN_KLASORLER and not k.startswith(".")
        ]
        for ad in adlar:
            p = Path(kok_dizin) / ad
            liste.append({"ad": p.relative_to(kok).as_posix(), "boyut": p.stat().st_size})
    return {"dosyalar": sorted(liste, key=lambda d: d["ad"])}


@app.get("/api/dosya")
def dosya(ad: str, indir: bool = False):
    """Tek dosyayı görüntüler (varsayılan) veya indirir (?indir=1)."""
    if DURUM.klasor_yolu is None:
        raise HTTPException(404, "aktif bir görev klasörü yok")
    kok = DURUM.klasor_yolu.resolve()
    hedef = (kok / ad).resolve()
    # Path traversal koruması: klasör dışına çıkan istekler reddedilir
    if not hedef.is_relative_to(kok) or not hedef.is_file():
        raise HTTPException(404, "dosya bulunamadı")
    if indir:
        return FileResponse(hedef, filename=hedef.name)
    return PlainTextResponse(hedef.read_text(encoding="utf-8", errors="replace"))


@app.get("/onizle/{dosya_yolu:path}")
def onizle(dosya_yolu: str):
    """Görev klasörünü statik site gibi sunar (canlı önizleme).

    HTML doğru content-type ile döndürülür; içindeki göreli style.css/script.js
    de bu kökten (/onizle/...) çözülür, böylece çok dosyalı site TAM çalışır.
    Yalnızca aktif görev klasörünün içi sunulur (path traversal koruması).
    """
    if DURUM.klasor_yolu is None:
        raise HTTPException(404, "aktif bir görev klasörü yok")
    kok = DURUM.klasor_yolu.resolve()
    hedef = (kok / dosya_yolu).resolve()
    if not hedef.is_relative_to(kok) or not hedef.is_file():
        raise HTTPException(404, "dosya bulunamadı")
    tur, _ = mimetypes.guess_type(str(hedef))
    return FileResponse(hedef, media_type=tur or "text/plain")


@app.get("/api/saglik")
def saglik():
    proxy_url = os.environ.get("FCC_PROXY_URL", VARSAYILAN_PROXY_URL)
    try:
        httpx.get(f"{proxy_url.rstrip('/')}/health", timeout=3.0)
        proxy = True
    except httpx.TransportError:
        proxy = False
    return {"api": True, "proxy": proxy}
