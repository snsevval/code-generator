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
import subprocess
import sys
import threading
from pathlib import Path

import mimetypes

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from orchestrator.calisma_alani import gorev_klasoru_sec
from orchestrator.fullstack_runner import fastapi_uygulamasi_bul
from orchestrator.llm_client import VARSAYILAN_PROXY_URL
from orchestrator.loop import IptalEdildi, Orkestrator
from orchestrator.proje import ProjeOrkestratoru
from orchestrator.playbook import gorevi_zenginlestir as playbook_zenginlestir
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
    # True: AYNI proje klasöründe devam — mevcut dosyalar korunur, yalnızca istenen
    # değişiklik uygulanır ("arka planı değiştir", "buton ekle" gibi takip istekleri)
    takip: bool = False


class OnayKarari(BaseModel):
    devam: bool


class OnizlemeIstegi(BaseModel):
    # Görev klasörüne göreli çalışma dizini (Vite projesi alt klasördeyse, ör. "counter-app")
    calisma_dizini: str = ""


ONAY_ZAMAN_ASIMI_SN = 3600.0  # onay bu süre içinde gelmezse zincir güvenli tarafta durur
ONIZLEME_PORT = 4173  # canlı önizleme sunucusunun sabit portu
ONIZLEME_KOMUTU = f"npm run dev -- --port {ONIZLEME_PORT} --host 127.0.0.1"


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
        # Canlı önizleme sunucusu (doğrulama sunucularından ayrı, tek aktif, açık kalır)
        self.onizleme_yoneticisi = None
        self.onizleme_url: str | None = None
        # Önizleme backend'i: başarılı fullstack/backend görevden sonra dinamik portta
        # açık kalır ki göz ikonu bağlı uygulamayı açsın (doğrulama sunucularından AYRI;
        # Runner'ınki iş sonunda kapanır, bu kalır)
        self.onizleme_backend_yoneticisi = None
        self.onizleme_backend_url: str | None = None
        # Takip modu (iteratif geliştirme): aynı proje üstündeki istek geçmişi +
        # ilk görevin playbook tipi (takiplerde doğrulama tipi tutarlı kalsın —
        # "rengi değiştir" bile fullstack olarak yeniden doğrulanır)
        self.sohbet: list[dict] = []  # {"istek": str, "basarili": bool}
        self.proje_tipi: str | None = None
        # İptal: kullanıcı yanlış/istenmeyen görevi durdurabilsin (orkestratör
        # işbirlikçi olarak bir sonraki aşama/tool turunda temiz durur)
        self.iptal_istendi = False


DURUM = _Durum()


def _gorev_kos(istek: GorevIstegi) -> None:
    """Arka plan iş parçacığı: görevi koşar, durumu günceller."""
    try:
        if istek.model:
            os.environ["FCC_MODEL"] = istek.model
        taban = Path(os.environ.get("FCC_WORKSPACE", "workspace")).resolve()
        # Görev başına izole klasör; TAKİP modunda ise AYNI klasörde devam edilir
        # (mevcut dosyalar korunur, yalnızca istenen değişiklik uygulanır)
        ws = gorev_klasoru_sec(
            taban, devam=istek.devam or istek.takip, proje=istek.proje
        )
        DURUM.klasor = f"{taban.name}/{ws.name}"
        DURUM.klasor_yolu = ws
        runner = DockerShellRunner(ws) if istek.docker else None
        log = lambda satir: DURUM.log.append(satir)  # noqa: E731
        ork = ORKESTRATOR_FABRIKASI(ws, ToolExecutor(ws, shell_runner=runner), log)
        # İşbirlikçi durdurma: gerçek orkestratörde iptal_kontrol var; bazı test
        # sahteleri attribute kabul etmez → savunmacı ata (o zaman iptal edilemez)
        try:
            ork.iptal_kontrol = lambda: DURUM.iptal_istendi
        except (AttributeError, TypeError):
            pass
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
        # Playbook: teknik tarif (portlar, araç akışı, doğrulama) otomatik eklenir —
        # kullanıcının mühendislik detayı yazması gerekmez
        gorev_metni, playbook_adi = playbook_zenginlestir(gorev_metni)
        if playbook_adi:
            log(f"[tarif] '{playbook_adi}' playbook'u göreve eklendi (portlar + araç akışı).")
        if istek.takip:
            # Takip: doğrulama tipi İLK görevden miras kalır ("rengi değiştir" gibi
            # kısa istekler playbook tetiklemese bile proje fullstack olarak doğrulanır)
            if playbook_adi is None:
                playbook_adi = DURUM.proje_tipi
            # Bağlam önsözü: mevcut dosyalar + önceki istekler + DEĞİŞTİR talimatı
            gorev_metni = _takip_onsozu(ws) + gorev_metni
            log("[takip] mevcut proje üzerinde çalışılıyor (dosyalar korunur).")
        else:
            DURUM.sohbet = []  # yeni proje: istek geçmişi sıfırlanır
        DURUM.proje_tipi = playbook_adi or DURUM.proje_tipi
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
            # "backend" tipinde doğrulama deterministik Runner'a gider (model
            # validator devre dışı) — sahte-BASARILI ve validator debelenmesini önler
            ork._dogrulama_tipi = playbook_adi
            # Takipte codegen hiçbir dosyayı değiştirmezse görev başarılı SAYILMAZ
            ork._takip = istek.takip
            state = ork.gorev_calistir(gorev_metni, devam=istek.devam)
            DURUM.sonuc = {
                "proje": False,
                "dogrulama_gecti": state.ciktilar.get("dogrulama_gecti") == "True",
                "debug_turu": state.debug_turu,
                "reviewer": state.ciktilar.get("reviewer", ""),
                "plan": state.ciktilar.get("planner", ""),
            }
            # Önizleme: fullstack/backend'de backend'i canlı bırak ki göz ikonu açsın.
            # ÖNEMLİ: doğrulama başarısız olsa BİLE dene — uygulama çalışıyorsa (backend
            # ayağa kalkıp serve ediyorsa) kullanıcı görebilmeli. Sırf test dosyası bozuk
            # diye çalışan uygulamanın önizlemesini kapatmak yanlıştı. _onizleme_backendini_
            # baslat zaten yalnızca backend GERÇEKTEN başlarsa URL set eder (bozuksa None).
            if playbook_adi in ("fullstack", "backend"):
                _onizleme_backendini_baslat(ws)
                if DURUM.onizleme_backend_url:
                    if DURUM.sonuc["dogrulama_gecti"]:
                        log(f"[önizleme] backend canlı: {DURUM.onizleme_backend_url} — "
                            "göz ikonuyla açınca liste/ekle/sil çalışır.")
                    else:
                        log(f"[önizleme] uygulama çalışıyor (testler geçmedi) — göz "
                            f"ikonuyla görebilirsin: {DURUM.onizleme_backend_url}")
            # İstek geçmişi: takip önsözünde ve UI thread'inde kullanılır
            DURUM.sohbet.append(
                {"istek": istek.gorev, "basarili": DURUM.sonuc["dogrulama_gecti"]}
            )
    except IptalEdildi:
        DURUM.hata = "Görev iptal edildi."
        log("[iptal] görev kullanıcı tarafından durduruldu.")
    except Exception as e:  # UI'ye okunur hata taşınır
        DURUM.hata = f"{type(e).__name__}: {e}"
    finally:
        DURUM.iptal_istendi = False
        DURUM.calisiyor = False


def _takip_onsozu(ws: Path) -> str:
    """Takip görevine eklenen bağlam önsözü: mevcut dosyalar + geçmiş + DEĞİŞTİR talimatı.

    Model sıfırdan yazmasın; mevcut projeyi okuyup yalnızca istenen değişikliği
    yapsın diye. Dosya listesi diskten (gerçek durum), istek geçmişi DURUM.sohbet'ten.
    """
    dosyalar = sorted(
        p.relative_to(ws).as_posix()
        for p in ws.rglob("*")
        if p.is_file()
        and not any(k in p.parts for k in GIZLENEN_KLASORLER)
        and not p.name.startswith(".")
    )[:40]
    gecmis = "\n".join(
        f"  {i + 1}. {s['istek'][:120]}" for i, s in enumerate(DURUM.sohbet[-5:])
    )
    return (
        "[TAKİP GÖREVİ — MEVCUT PROJE ÜZERİNDE ÇALIŞ]\n"
        "Bu klasörde daha önce üretilmiş ÇALIŞAN bir proje var. SIFIRDAN YAZMA:\n"
        "önce read_file ile ilgili dosyaları incele, sonra istenen değişikliği "
        "edit_file ile uygula (küçük değişiklikte write_file ile tüm dosyayı yeniden "
        "yazma). İstenmeyen hiçbir şeyi değiştirme; çalışan özellikleri koru.\n"
        f"Mevcut dosyalar: {', '.join(dosyalar) if dosyalar else '(boş)'}\n"
        + (f"Önceki istekler:\n{gecmis}\n" if gecmis else "")
        + "\nYENİ İSTEK: "
    )


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
        if not istek.takip:
            # Yeni proje: önceki görevin klasörü/dosyaları arayüzde kalmasın
            # (takipte AYNI klasör sürer — dosyalar bilerek korunur)
            DURUM.klasor = None
            DURUM.klasor_yolu = None
    # Önizlemeleri kapat: dinamik portlar serbest kalsın + sızıntı önlensin
    # (takipte de kapatılır — görev sonunda güncel haliyle yeniden başlar)
    _onizlemeyi_durdur()
    _onizleme_backendini_durdur()
    threading.Thread(target=_gorev_kos, args=(istek,), daemon=True).start()
    return {"baslatildi": True, "gorev": istek.gorev}


@app.post("/api/iptal")
def gorev_iptal():
    """Çalışan görevi iptal eder (işbirlikçi: orkestratör bir sonraki aşama/tool
    turunda temiz durur). Yanlış görev gönderildiğinde yeni projeye geçebilmek için."""
    if not DURUM.calisiyor:
        return {"iptal": False, "mesaj": "çalışan görev yok"}
    DURUM.iptal_istendi = True
    DURUM.log.append("[iptal] durdurma istendi — mevcut adım bitince duracak...")
    return {"iptal": True}


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
        "onizleme_url": DURUM.onizleme_url,
        "onizleme_backend_url": DURUM.onizleme_backend_url,
        "sohbet": DURUM.sohbet,
        "iptal_istendi": DURUM.iptal_istendi,
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
    # Tek-origin projede index.html göreli fetch kullanır; /onizle statik rotasından
    # açılırsa istekler 8090'a gidip 404 olur. Canlı önizleme backend'i varsa HTML
    # isteklerini oraya YÖNLENDİR — göz ikonu, eski link, kas hafızası hepsi çalışır.
    if DURUM.onizleme_backend_url and dosya_yolu.lower().endswith((".html", ".htm")):
        return RedirectResponse(DURUM.onizleme_backend_url)
    kok = DURUM.klasor_yolu.resolve()
    hedef = (kok / dosya_yolu).resolve()
    if not hedef.is_relative_to(kok) or not hedef.is_file():
        raise HTTPException(404, "dosya bulunamadı")
    tur, _ = mimetypes.guess_type(str(hedef))
    return FileResponse(hedef, media_type=tur or "text/plain")


@app.post("/api/onizle-baslat")
def onizle_baslat(istek: OnizlemeIstegi):
    """Vite/dev-server gerektiren projeyi canlı başlatır (açık kalır).

    Doğrulama sunucularından ayrı — tek aktif önizleme: yeni başlatınca eski
    kapanır (sızıntı yok). package.json içeren projeler için UI'deki 'Canlı
    Önizle' düğmesi bunu çağırır; node_modules kurulu olmalı.
    """
    from orchestrator.sunucu import SunucuYoneticisi

    if DURUM.klasor_yolu is None:
        raise HTTPException(404, "aktif bir görev klasörü yok")
    kok = DURUM.klasor_yolu.resolve()
    hedef = (kok / istek.calisma_dizini).resolve()
    if not hedef.is_relative_to(kok) or not hedef.is_dir():
        raise HTTPException(404, "çalışma dizini bulunamadı")
    if not (hedef / "package.json").is_file():
        raise HTTPException(400, "bu klasörde package.json yok (dev sunucusu gerektirmez)")

    # Önceki önizlemeyi kapat (tek aktif)
    _onizlemeyi_durdur()
    yonetici = SunucuYoneticisi(hedef)
    mesaj = yonetici.baslat(ONIZLEME_KOMUTU, ONIZLEME_PORT)
    if mesaj.startswith("HATA"):
        raise HTTPException(400, mesaj)
    DURUM.onizleme_yoneticisi = yonetici
    DURUM.onizleme_url = f"http://localhost:{ONIZLEME_PORT}"
    return {"url": DURUM.onizleme_url}


@app.post("/api/onizle-durdur")
def onizle_durdur():
    _onizlemeyi_durdur()
    _onizleme_backendini_durdur()
    return {"durduruldu": True}


def _onizlemeyi_durdur() -> None:
    if DURUM.onizleme_yoneticisi is not None:
        DURUM.onizleme_yoneticisi.hepsini_durdur()
        DURUM.onizleme_yoneticisi = None
        DURUM.onizleme_url = None


def _onizleme_backendini_baslat(ws: Path) -> None:
    """Görevin backend'ini {BACKEND_PORT}'te önizleme için canlı başlatır (varsa).

    Doğrulama sunucularından AYRI ve açık kalır ki /onizle/index.html'in fetch'i
    canlı backend'e ulaşsın. FastAPI modülü yoksa sessizce atlar (statik/vite görevi).
    """
    from orchestrator.sunucu import SunucuYoneticisi, bos_port_bul

    _onizleme_backendini_durdur()  # tek aktif önizleme backend'i
    uygulama = fastapi_uygulamasi_bul(ws)
    if uygulama is None:
        return
    modul, app_degiskeni = uygulama
    port = bos_port_bul()  # dinamik port — sabit port çakışması yok
    komut = (
        f'"{sys.executable}" -m uvicorn {modul}:{app_degiskeni} '
        f"--port {port} --host 127.0.0.1"
    )
    yonetici = SunucuYoneticisi(ws)
    mesaj = yonetici.baslat(komut, port)
    if mesaj.startswith("HATA"):
        return
    DURUM.onizleme_backend_yoneticisi = yonetici
    # Tek-origin: bu backend index.html'i de `/` kökünde servis eder → göz ikonu bunu açar
    DURUM.onizleme_backend_url = f"http://localhost:{port}"


def _onizleme_backendini_durdur() -> None:
    if DURUM.onizleme_backend_yoneticisi is not None:
        DURUM.onizleme_backend_yoneticisi.hepsini_durdur()
        DURUM.onizleme_backend_yoneticisi = None
        DURUM.onizleme_backend_url = None


def _gorev_git(*args: str) -> subprocess.CompletedProcess:
    """Aktif görev klasörünün KENDİ git reposunda komut çalıştırır."""
    return subprocess.run(
        ["git", *args],
        cwd=DURUM.klasor_yolu,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
    )


@app.get("/api/degisiklikler")
def degisiklikler():
    """Son commit'in diff'ini döndürür ("Değişiklikleri Gör").

    Görev klasörünün kendi reposu (git_deposu) her görevi commit'ler; son commit
    = son görevin/takibin dokunduğu her şey.
    """
    if DURUM.klasor_yolu is None or not (DURUM.klasor_yolu / ".git").exists():
        raise HTTPException(404, "aktif görevde git tarihçesi yok")
    try:
        sonuc = _gorev_git("show", "--stat", "-p", "--no-color", "HEAD")
    except (OSError, subprocess.SubprocessError) as e:
        raise HTTPException(500, f"git çalıştırılamadı: {e}")
    if sonuc.returncode != 0:
        raise HTTPException(404, "gösterilecek commit yok")
    return PlainTextResponse(sonuc.stdout[:200_000])


@app.post("/api/geri-al")
def geri_al():
    """Son değişikliği geri alır ("Geri Al") ve önizleme backend'ini yeniler.

    git revert: tarihçe korunur (reset'ten güvenli); revert de bir commit olduğundan
    tekrar 'Geri Al' ile geri-alınan geri getirilebilir.
    """
    if DURUM.calisiyor:
        raise HTTPException(409, "görev çalışırken geri alınamaz")
    if DURUM.klasor_yolu is None or not (DURUM.klasor_yolu / ".git").exists():
        raise HTTPException(404, "aktif görevde git tarihçesi yok")
    try:
        sonuc = _gorev_git("revert", "--no-edit", "HEAD")
    except (OSError, subprocess.SubprocessError) as e:
        raise HTTPException(500, f"git çalıştırılamadı: {e}")
    if sonuc.returncode != 0:
        raise HTTPException(
            409, f"geri alma başarısız: {(sonuc.stderr or sonuc.stdout)[:300]}"
        )
    # Önizleme, dosyaların güncel (geri alınmış) haliyle yeniden başlasın
    _onizleme_backendini_baslat(DURUM.klasor_yolu)
    return {"geri_alindi": True, "onizleme_backend_url": DURUM.onizleme_backend_url}


@app.get("/api/saglik")
def saglik():
    proxy_url = os.environ.get("FCC_PROXY_URL", VARSAYILAN_PROXY_URL)
    try:
        httpx.get(f"{proxy_url.rstrip('/')}/health", timeout=3.0)
        proxy = True
    except httpx.TransportError:
        proxy = False
    return {"api": True, "proxy": proxy}
