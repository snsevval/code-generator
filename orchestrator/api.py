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


class _Durum:
    """Süreç içi tekil görev durumu (UI'nin yokladığı her şey)."""

    def __init__(self):
        self.kilit = threading.Lock()
        self.calisiyor = False
        self.gorev: str | None = None
        self.log: list[str] = []
        self.hata: str | None = None
        self.sonuc: dict | None = None


DURUM = _Durum()


def _gorev_kos(istek: GorevIstegi) -> None:
    """Arka plan iş parçacığı: görevi koşar, durumu günceller."""
    try:
        if istek.model:
            os.environ["FCC_MODEL"] = istek.model
        ws = Path(os.environ.get("FCC_WORKSPACE", "workspace")).resolve()
        ws.mkdir(parents=True, exist_ok=True)
        runner = DockerShellRunner(ws) if istek.docker else None
        ork = ORKESTRATOR_FABRIKASI(
            ws,
            ToolExecutor(ws, shell_runner=runner),
            lambda satir: DURUM.log.append(satir),
        )
        state = ork.gorev_calistir(istek.gorev, devam=istek.devam)
        DURUM.sonuc = {
            "dogrulama_gecti": state.ciktilar.get("dogrulama_gecti") == "True",
            "debug_turu": state.debug_turu,
            "reviewer": state.ciktilar.get("reviewer", ""),
            "plan": state.ciktilar.get("planner", ""),
        }
    except Exception as e:  # UI'ye okunur hata taşınır
        DURUM.hata = f"{type(e).__name__}: {e}"
    finally:
        DURUM.calisiyor = False


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
    }


@app.get("/api/saglik")
def saglik():
    proxy_url = os.environ.get("FCC_PROXY_URL", VARSAYILAN_PROXY_URL)
    try:
        httpx.get(f"{proxy_url.rstrip('/')}/health", timeout=3.0)
        proxy = True
    except httpx.TransportError:
        proxy = False
    return {"api": True, "proxy": proxy}
