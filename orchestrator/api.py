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

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orchestrator.llm_client import VARSAYILAN_PROXY_URL
from orchestrator.loop import Orkestrator
from orchestrator.proje import ProjeOrkestratoru
from orchestrator.tool_executor import DockerShellRunner, ToolExecutor

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


DURUM = _Durum()


def _gorev_kos(istek: GorevIstegi) -> None:
    """Arka plan iş parçacığı: görevi koşar, durumu günceller."""
    try:
        if istek.model:
            os.environ["FCC_MODEL"] = istek.model
        ws = Path(os.environ.get("FCC_WORKSPACE", "workspace")).resolve()
        ws.mkdir(parents=True, exist_ok=True)
        runner = DockerShellRunner(ws) if istek.docker else None
        log = lambda satir: DURUM.log.append(satir)  # noqa: E731
        ork = ORKESTRATOR_FABRIKASI(ws, ToolExecutor(ws, shell_runner=runner), log)
        DURUM.istemci = getattr(ork, "istemci", None)
        if istek.proje:
            onay = _onay_bekle if istek.onayli else None
            proje = ProjeOrkestratoru(ws, orkestrator=ork, log=log, onay_callback=onay)
            pstate = proje.hedef_calistir(istek.gorev, devam=istek.devam)
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
            state = ork.gorev_calistir(istek.gorev, devam=istek.devam)
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


# Testlerin sahte orkestratör enjekte edebilmesi için modül düzeyinde
ORKESTRATOR_FABRIKASI = _varsayilan_fabrika


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
    }


@app.post("/api/onay")
def onay_ver(karar: OnayKarari):
    if DURUM.onay_bekleyen is None:
        raise HTTPException(409, "onay bekleyen bir alt görev yok")
    DURUM.onay_karari = karar.devam
    DURUM.onay_olayi.set()
    return {"alindi": True, "devam": karar.devam}


@app.get("/api/saglik")
def saglik():
    proxy_url = os.environ.get("FCC_PROXY_URL", VARSAYILAN_PROXY_URL)
    try:
        httpx.get(f"{proxy_url.rstrip('/')}/health", timeout=3.0)
        proxy = True
    except httpx.TransportError:
        proxy = False
    return {"api": True, "proxy": proxy}
