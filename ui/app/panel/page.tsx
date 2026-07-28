"use client";

// Sohbet ekranı (modern konuşma arayüzü): kullanıcı mesajları sağda balon, sistemin
// çalışması solda "asistan" mesajında CANLI DURUM KARTLARI (ham log değil). Ham log +
// token "Detayları göster" altında. Alt sabit kompozer; düzenlemeler (takip) aynı sohbette.
// Tüm veri gerçek: /api/durum. Backend'e dokunulmaz.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import styles from "./page.module.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8090";
const MAKS = 4000;

type AltGorev = { id: number; gorev: string; durum: string };
type Sonuc = {
  proje: boolean;
  dogrulama_gecti: boolean;
  debug_turu?: number;
  reviewer?: string;
  plan?: string;
  alt_gorevler?: AltGorev[];
  entegrasyon?: string;
};
type Kullanim = { istek: number; girdi: number; cikti: number };
type Durum = {
  calisiyor: boolean;
  gorev: string | null;
  log: string[];
  hata: string | null;
  sonuc: Sonuc | null;
  onay_bekleyen: { id: number; gorev: string } | null;
  kullanim: Kullanim | null;
  klasor: string | null;
  onizleme_url: string | null;
  onizleme_backend_url: string | null;
  sohbet: { istek: string; basarili: boolean }[];
  iptal_istendi: boolean;
};
type Saglik = { api: boolean; proxy: boolean };
type Dosya = { ad: string; boyut: number };

// --- Yardımcılar ---

function tokenBicimle(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

function boyutBicimle(bayt: number): string {
  if (bayt >= 1024 * 1024) return `${(bayt / 1024 / 1024).toFixed(1)} MB`;
  if (bayt >= 1024) return `${(bayt / 1024).toFixed(1)} KB`;
  return `${bayt} B`;
}

function satirSinifi(satir: string): string {
  if (satir.includes("[planner]")) return styles.lPlanner;
  if (satir.includes("[codegen]")) return styles.lCodegen;
  if (satir.includes("[runner]")) return styles.lRunner;
  if (satir.includes("[debugger]")) return styles.lDebugger;
  if (satir.includes("[reviewer]")) return styles.lReviewer;
  if (satir.includes("[önizleme]")) return styles.lOnizleme;
  if (satir.includes("[orkestratör]") || satir.includes("[git]") || satir.includes("[iptal]"))
    return styles.lOrk;
  return "";
}

// Logdan yazılan dosya adlarını çıkar (write_file çağrılarından)
function yazilanDosyalar(log: string[]): string[] {
  const set = new Set<string>();
  const re = /'path':\s*'([^']*\.(?:py|html|css|js|ts|txt|json|md|cpp|h|ini))'/g;
  for (const s of log) {
    if (!s.includes("write_file")) continue;
    let m: RegExpExecArray | null;
    while ((m = re.exec(s)) !== null) set.add(m[1]);
  }
  return [...set];
}

type KartDurum = "bekliyor" | "calisiyor" | "tamam" | "basarisiz";
type Adim = { anahtar: string; etiket: string; durum: KartDurum; not?: string };

// Ham logdan kullanıcıya dönük sıralı durum kartları türet
function adimKartlari(durum: Durum | null): Adim[] {
  const log = durum?.log ?? [];
  const metin = log.join("\n");
  const gordu = (s: string) => metin.includes(s);
  const calisiyor = !!durum?.calisiyor;
  const final: KartDurum | null = durum?.sonuc
    ? durum.sonuc.dogrulama_gecti
      ? "tamam"
      : "basarisiz"
    : durum?.hata
      ? "basarisiz"
      : null;

  const adimlar: Adim[] = [];

  // 1) Plan
  adimlar.push({
    anahtar: "plan",
    etiket: gordu("[planner] bitti") ? "Plan hazır" : "Plan hazırlanıyor",
    durum: gordu("[planner] bitti") ? "tamam" : gordu("[planner]") ? "calisiyor" : "bekliyor",
  });

  // 2) Dosyalar
  const dosyalar = yazilanDosyalar(log);
  adimlar.push({
    anahtar: "kod",
    etiket: gordu("[codegen] bitti") ? "Dosyalar oluşturuldu" : "Dosyalar oluşturuluyor",
    durum: gordu("[codegen] bitti") ? "tamam" : gordu("[codegen]") ? "calisiyor" : "bekliyor",
    not: dosyalar.length ? dosyalar.join(" · ") : undefined,
  });

  // 3) Testler & doğrulama
  const dogTamam = gordu("doğrulama: BAŞARILI");
  const dogKaldi = gordu("doğrulama: BAŞARISIZ");
  adimlar.push({
    anahtar: "dogrulama",
    etiket: dogTamam ? "Testler ve doğrulama geçti" : "Testler ve doğrulama",
    durum: dogTamam
      ? "tamam"
      : dogKaldi && final === "basarisiz"
        ? "basarisiz"
        : gordu("[runner]")
          ? "calisiyor"
          : "bekliyor",
  });

  // 4) Hata düzeltme (yalnız debugger devreye girdiyse)
  if (gordu("[debugger]") || gordu("→ debugger")) {
    adimlar.push({
      anahtar: "debug",
      etiket: "Hata düzeltiliyor",
      durum: calisiyor ? "calisiyor" : final === "tamam" ? "tamam" : "basarisiz",
    });
  }

  // 5) Önizleme (varsa)
  if (gordu("[önizleme] backend canlı") || durum?.onizleme_backend_url) {
    adimlar.push({ anahtar: "onizleme", etiket: "Önizleme hazır", durum: "tamam" });
  }

  // 6) Final
  if (final) {
    adimlar.push({
      anahtar: "final",
      etiket: final === "tamam" ? "Tamamlandı" : durum?.hata ? "Hata oluştu" : "Doğrulama kaldı",
      durum: final,
      not: durum?.hata ?? undefined,
    });
  }
  return adimlar;
}

// --- SVG ikonlar (tek çizgi ailesi, emoji YOK) ---
const Spinner = ({ boyut = 16 }: { boyut?: number }) => (
  <svg className={styles.spinner} width={boyut} height={boyut} viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
    <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
  </svg>
);
const IkonTamam = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="10" fill="#15803d" fillOpacity="0.14" />
    <path d="m8 12.5 2.5 2.5L16 9.5" stroke="#15803d" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IkonHata = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="10" fill="#dc3a52" fillOpacity="0.14" />
    <path d="m9 9 6 6M15 9l-6 6" stroke="#dc3a52" strokeWidth="2" strokeLinecap="round" />
  </svg>
);
const IkonBekliyor = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="9" stroke="#c8c8c8" strokeWidth="2" strokeDasharray="3 3" />
  </svg>
);
const IkonGonder = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IkonYeni = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);
const IkonGoz = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
  </svg>
);
const IkonDosya = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    <path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
  </svg>
);
const IkonDiff = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M6 3v12a3 3 0 0 0 3 3h6M6 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm12 18a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm0-4V9m0 0 3 3m-3-3-3 3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IkonGeriAl = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M9 14 4 9l5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M4 9h11a5 5 0 0 1 0 10h-1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IkonIptal = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);
const IkonIndir = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M12 4v11m0 0 4-4m-4 4-4-4M5 19h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IkonAsistan = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
    <rect x="4" y="7" width="16" height="12" rx="3" stroke="#15803d" strokeWidth="1.8" />
    <path d="M12 3v4M9 13h.01M15 13h.01" stroke="#15803d" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);
const IkonMenu = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);
const IkonGunes = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="2" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);
const IkonAy = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
  </svg>
);

const DURUM_KART_IKON: Record<KartDurum, React.ReactNode> = {
  bekliyor: <IkonBekliyor />,
  calisiyor: <Spinner boyut={18} />,
  tamam: <IkonTamam />,
  basarisiz: <IkonHata />,
};

export default function Sohbet() {
  const [durum, setDurum] = useState<Durum | null>(null);
  const [saglik, setSaglik] = useState<Saglik | null>(null);
  const [dosyalar, setDosyalar] = useState<Dosya[]>([]);
  const [mesaj, setMesaj] = useState("");
  const [yeniProje, setYeniProje] = useState(false);
  const [tasarim, setTasarim] = useState(false);
  const [proje, setProje] = useState(false);
  const [docker, setDocker] = useState(false);
  const [gonderimHatasi, setGonderimHatasi] = useState<string | null>(null);
  const [dosyalarAcik, setDosyalarAcik] = useState(false);
  const [onizlemeYukleniyor, setOnizlemeYukleniyor] = useState(false);
  const [degisiklik, setDegisiklik] = useState<string | null>(null);
  const [tema, setTema] = useState<"aydinlik" | "karanlik">("aydinlik");
  const [sidebarAcik, setSidebarAcik] = useState(true);
  const sohbetSonu = useRef<HTMLDivElement>(null);

  // Tema + sidebar tercihi localStorage'dan (yenilemede korunur)
  useEffect(() => {
    const t = localStorage.getItem("cg-tema");
    if (t === "karanlik" || t === "aydinlik") setTema(t);
    if (localStorage.getItem("cg-sidebar") === "kapali") setSidebarAcik(false);
  }, []);

  function temaDegistir() {
    setTema((t) => {
      const n = t === "karanlik" ? "aydinlik" : "karanlik";
      localStorage.setItem("cg-tema", n);
      return n;
    });
  }
  function sidebarTogle() {
    setSidebarAcik((v) => {
      localStorage.setItem("cg-sidebar", v ? "kapali" : "acik");
      return !v;
    });
  }

  const durumuGetir = useCallback(async () => {
    try {
      const y = await fetch(`${API}/api/durum`);
      setDurum(await y.json());
    } catch {
      setDurum(null);
    }
  }, []);

  useEffect(() => {
    const sagligiGetir = async () => {
      try {
        setSaglik(await (await fetch(`${API}/api/saglik`)).json());
      } catch {
        setSaglik(null);
      }
    };
    sagligiGetir();
    durumuGetir();
    const s = setInterval(sagligiGetir, 10000);
    return () => clearInterval(s);
  }, [durumuGetir]);

  useEffect(() => {
    if (!durum?.calisiyor) return;
    const s = setInterval(durumuGetir, 1500);
    return () => clearInterval(s);
  }, [durum?.calisiyor, durumuGetir]);

  useEffect(() => {
    sohbetSonu.current?.scrollIntoView({ behavior: "smooth" });
  }, [durum?.log.length, durum?.gorev, yeniProje]);

  useEffect(() => {
    if (!durum?.klasor) {
      setDosyalar([]);
      return;
    }
    fetch(`${API}/api/dosyalar`)
      .then((y) => y.json())
      .then((v) => setDosyalar(v.dosyalar ?? []))
      .catch(() => setDosyalar([]));
  }, [durum?.klasor, durum?.log.length, durum?.calisiyor]);

  // Yeni proje mi yoksa mevcut projeye takip mi? (klasör varsa ve "Yeni sohbet" denmediyse takip)
  const takipModu = !yeniProje && !!durum?.klasor && !durum?.calisiyor;

  async function istekGonder(metin: string, takip: boolean) {
    setGonderimHatasi(null);
    const y = await fetch(`${API}/api/gorev`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        takip
          ? { gorev: metin, takip: true }
          : { gorev: metin, tasarim, proje, docker, takip: false },
      ),
    });
    if (!y.ok) {
      const veri = await y.json().catch(() => null);
      throw new Error(veri?.detail ?? `HTTP ${y.status}`);
    }
    await durumuGetir();
  }

  async function mesajGonder(e: React.FormEvent) {
    e.preventDefault();
    const metin = mesaj.trim();
    if (!metin || durum?.calisiyor) return;
    try {
      await istekGonder(metin, takipModu);
      setMesaj("");
      setYeniProje(false);
      setDosyalarAcik(false);
    } catch (err) {
      setGonderimHatasi(err instanceof Error ? err.message : String(err));
    }
  }

  function yeniSohbet() {
    setYeniProje(true);
    setMesaj("");
    setGonderimHatasi(null);
    setDosyalarAcik(false);
  }

  async function iptalEt() {
    try {
      await fetch(`${API}/api/iptal`, { method: "POST" });
      await durumuGetir();
    } catch {
      /* yoklama sürüyor */
    }
  }

  async function onayGonder(devam: boolean) {
    try {
      await fetch(`${API}/api/onay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ devam }),
      });
      await durumuGetir();
    } catch {
      /* yoklama sürüyor */
    }
  }

  const projeKlasoru = useMemo(() => {
    const pkg = dosyalar.find((d) => d.ad.endsWith("package.json"));
    if (!pkg) return null;
    return pkg.ad.includes("/") ? pkg.ad.slice(0, pkg.ad.lastIndexOf("/")) : "";
  }, [dosyalar]);

  async function onizle() {
    // Tek-origin backend önizlemesi varsa onu aç; yoksa vite/dev sunucusu başlat
    if (durum?.onizleme_backend_url) {
      window.open(durum.onizleme_backend_url, "_blank", "noopener");
      return;
    }
    if (durum?.onizleme_url) {
      window.open(durum.onizleme_url, "_blank", "noopener");
      return;
    }
    if (projeKlasoru === null) {
      setGonderimHatasi("Açılacak canlı önizleme yok.");
      return;
    }
    setOnizlemeYukleniyor(true);
    try {
      const y = await fetch(`${API}/api/onizle-baslat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ calisma_dizini: projeKlasoru }),
      });
      const veri = await y.json();
      if (!y.ok) throw new Error(veri?.detail ?? `HTTP ${y.status}`);
      await durumuGetir();
      window.open(veri.url, "_blank", "noopener");
    } catch (err) {
      setGonderimHatasi(err instanceof Error ? err.message : String(err));
    } finally {
      setOnizlemeYukleniyor(false);
    }
  }

  async function degisiklikleriGor() {
    try {
      const y = await fetch(`${API}/api/degisiklikler`);
      if (!y.ok) throw new Error(`HTTP ${y.status}`);
      setDegisiklik(await y.text());
    } catch (err) {
      setDegisiklik(`Değişiklikler alınamadı: ${err instanceof Error ? err.message : err}`);
    }
  }

  async function geriAl() {
    if (!window.confirm("Son değişiklik geri alınsın mı? (git revert — güvenli, tekrar geri alınabilir)")) return;
    try {
      const y = await fetch(`${API}/api/geri-al`, { method: "POST" });
      if (!y.ok) {
        const v = await y.json().catch(() => null);
        throw new Error(v?.detail ?? `HTTP ${y.status}`);
      }
      await durumuGetir();
    } catch (err) {
      setGonderimHatasi(err instanceof Error ? err.message : String(err));
    }
  }

  // --- Türetilmiş görünüm verileri ---
  const kartlar = useMemo(() => adimKartlari(durum), [durum]);
  const konusmaVar = !yeniProje && !!durum?.gorev;
  const gecmis = durum?.sohbet ?? [];
  // "Yeni sohbet"te ana alan temizlenir (hoşgeldin); aksi halde geçmiş istekler +
  // canlı görev gösterilir. Son istek zaten canlı görevde göründüğü için tekrar edilmez.
  const gecmisGoster = yeniProje
    ? []
    : konusmaVar && durum?.gorev
      ? gecmis.slice(0, -1)
      : gecmis;

  const durumEtiketi = !durum
    ? "API kapalı"
    : durum.onay_bekleyen
      ? "Onay bekliyor"
      : durum.calisiyor
        ? "Çalışıyor"
        : durum.hata
          ? "Hata"
          : durum.sonuc
            ? durum.sonuc.dogrulama_gecti
              ? "Hazır"
              : "Doğrulama kaldı"
            : "Hazır";

  const k = durum?.kullanim;
  const bosDurum = !konusmaVar && gecmisGoster.length === 0;

  return (
    <div className={`${styles.kabuk} ${tema === "karanlik" ? styles.karanlik : ""}`}>
      {/* Üst çubuk */}
      <header className={styles.ust}>
        <div className={styles.marka}>
          <button className={styles.ikonBtn} onClick={sidebarTogle} aria-label="Kenar çubuğunu aç/kapa" title="Kenar çubuğu">
            <IkonMenu />
          </button>
          <a href="/" className={styles.markaAd}>code-generator</a>
          {durum?.klasor && <span className={styles.klasorEtiket}>{durum.klasor}</span>}
        </div>
        <div className={styles.ustSag}>
          <button
            className={styles.ikonBtn}
            onClick={temaDegistir}
            aria-label={tema === "karanlik" ? "Aydınlık temaya geç" : "Karanlık temaya geç"}
            title={tema === "karanlik" ? "Aydınlık tema" : "Karanlık tema"}
          >
            {tema === "karanlik" ? <IkonGunes /> : <IkonAy />}
          </button>
          <span className={`${styles.durumRozet} ${durum?.calisiyor ? styles.rozetAktif : durum?.hata ? styles.rozetKotu : styles.rozetIyi}`}>
            {durum?.calisiyor && <Spinner boyut={12} />} {durumEtiketi}
          </span>
          <span className={`${styles.saglik} ${saglik?.api ? styles.sIyi : styles.sKotu}`}>API</span>
          <span className={`${styles.saglik} ${saglik?.proxy ? styles.sIyi : styles.sKotu}`}>Proxy</span>
        </div>
      </header>

      <div className={`${styles.izgara} ${sidebarAcik ? "" : styles.izgaraDar}`}>
        {/* Sol sidebar */}
        {sidebarAcik && (
        <aside className={styles.yan}>
          <button className={styles.yeniBtn} onClick={yeniSohbet}>
            <IkonYeni /> Yeni sohbet
          </button>
          {durum?.klasor ? (
            <>
              <p className={styles.yanBaslik}>Bu proje</p>
              <ul className={styles.yanListe}>
                {gecmis.length === 0 && <li className={styles.yanBos}>Henüz istek yok</li>}
                {gecmis.map((s, i) => (
                  <li key={i} className={styles.yanOge}>
                    <span className={`${styles.yanNokta} ${s.basarili ? styles.nIyi : styles.nKotu}`} aria-hidden />
                    <span className={styles.yanMetin}>{s.istek}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className={styles.yanBos}>Görev göndererek yeni bir proje başlat.</p>
          )}
        </aside>
        )}

        {/* Orta: sohbet akışı */}
        <main className={styles.sohbet}>
          <div className={styles.akis}>
            {bosDurum && (
              <div className={styles.hosgeldin}>
                <IkonAsistan />
                <h1>Ne yapmak istersin?</h1>
                <p>Görevini doğal dille yaz — sistem kodu yazsın, test etsin, çalıştırıp doğrulasın. Sonra aynı sohbetten “şunu da ekle” diye devam edebilirsin.</p>
              </div>
            )}

            {/* Geçmiş istekler (kompakt) */}
            {gecmisGoster.map((s, i) => (
              <div key={`g${i}`} className={styles.tur}>
                <div className={styles.kullaniciBalon}>{s.istek}</div>
                <div className={styles.asistanMesaj}>
                  <span className={styles.asistanIkon}><IkonAsistan /></span>
                  <div className={styles.asistanGovde}>
                    <div className={`${styles.ozetCip} ${s.basarili ? styles.cipIyi : styles.cipKotu}`}>
                      {s.basarili ? <IkonTamam /> : <IkonHata />}
                      {s.basarili ? "Tamamlandı" : "Doğrulama kaldı"}
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {/* Güncel görev — tam canlı */}
            {konusmaVar && (
              <div className={styles.tur}>
                <div className={styles.kullaniciBalon}>{durum!.gorev}</div>
                <div className={styles.asistanMesaj}>
                  <span className={styles.asistanIkon}><IkonAsistan /></span>
                  <div className={styles.asistanGovde}>
                    <ul className={styles.kartlar} aria-live="polite">
                      {kartlar.map((a) => (
                        <li key={a.anahtar} className={`${styles.kart} ${styles[`d_${a.durum}`]}`}>
                          <span className={styles.kartIkon}>{DURUM_KART_IKON[a.durum]}</span>
                          <span className={styles.kartMetin}>
                            <span className={styles.kartEtiket}>{a.etiket}</span>
                            {a.not && <span className={styles.kartNot}>{a.not}</span>}
                          </span>
                        </li>
                      ))}
                    </ul>

                    {/* Onay bekleyen alt görev (proje modu) */}
                    {durum!.onay_bekleyen && (
                      <div className={styles.onay}>
                        <span>Alt görev {durum!.onay_bekleyen.id} bitti: {durum!.onay_bekleyen.gorev}</span>
                        <div className={styles.onayBtnlar}>
                          <button className={styles.btnBirincil} onClick={() => onayGonder(true)}>Devam et</button>
                          <button className={styles.btnTehlike} onClick={() => onayGonder(false)}>Durdur</button>
                        </div>
                      </div>
                    )}

                    {/* Detaylar: ham log + token */}
                    {durum!.log.length > 0 && (
                      <details className={styles.detay}>
                        <summary>Detayları göster</summary>
                        <div className={styles.log}>
                          {durum!.log.map((satir, i) => (
                            <div key={i} className={satirSinifi(satir)}>{satir}</div>
                          ))}
                          {durum!.calisiyor && <span className={styles.imlec}>▋</span>}
                        </div>
                        {k && k.istek > 0 && (
                          <div className={styles.token}>
                            <span>Giriş {tokenBicimle(k.girdi)}</span>
                            <span>Çıkış {tokenBicimle(k.cikti)}</span>
                            <span>İstek {k.istek}</span>
                          </div>
                        )}
                      </details>
                    )}

                    {/* Dosyalar (açılır) */}
                    {dosyalarAcik && dosyalar.length > 0 && (
                      <ul className={styles.dosyaListe}>
                        {dosyalar.map((d) => (
                          <li key={d.ad}>
                            <IkonDosya />
                            <a className={styles.dosyaAd} href={`${API}/api/dosya?ad=${encodeURIComponent(d.ad)}`} target="_blank" rel="noreferrer">{d.ad}</a>
                            <span className={styles.dosyaBoyut}>{boyutBicimle(d.boyut)}</span>
                            <a className={styles.dosyaIkon} href={`${API}/api/dosya?ad=${encodeURIComponent(d.ad)}&indir=1`} download={d.ad} aria-label={`${d.ad} indir`}><IkonIndir /></a>
                          </li>
                        ))}
                      </ul>
                    )}

                    {/* Aksiyon butonları — görev bitince */}
                    {!durum!.calisiyor && (durum!.sonuc || durum!.hata) && (
                      <div className={styles.butonlar}>
                        <button className={styles.btnBirincil} onClick={onizle} disabled={onizlemeYukleniyor}>
                          {onizlemeYukleniyor ? <><Spinner boyut={14} /> Açılıyor…</> : <><IkonGoz /> Önizle</>}
                        </button>
                        <button className={styles.btnIkincil} onClick={() => setDosyalarAcik((v) => !v)}>
                          <IkonDosya /> Dosyalar{dosyalar.length ? ` (${dosyalar.length})` : ""}
                        </button>
                        <button className={styles.btnIkincil} onClick={degisiklikleriGor}>
                          <IkonDiff /> Değişiklikler
                        </button>
                        <button className={styles.btnTehlike} onClick={geriAl}>
                          <IkonGeriAl /> Geri Al
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {gonderimHatasi && <p className={styles.hataSatir} role="alert">{gonderimHatasi}</p>}
            <div ref={sohbetSonu} />
          </div>

          {/* Sabit kompozer */}
          <div className={styles.kompozerSar}>
            <form className={styles.kompozer} onSubmit={mesajGonder}>
              <textarea
                className={styles.giris}
                value={mesaj}
                onChange={(e) => setMesaj(e.target.value.slice(0, MAKS))}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void mesajGonder(e);
                  }
                }}
                placeholder={takipModu ? "Değişiklik iste… (örn. arka planı koyu yap, buton ekle)" : "Görevini yaz… (örn. FastAPI ile todo uygulaması yap)"}
                rows={1}
                disabled={durum?.calisiyor ?? false}
              />
              {durum?.calisiyor ? (
                <button type="button" className={styles.iptalBtn} onClick={iptalEt} disabled={durum?.iptal_istendi ?? false} aria-label="İptal">
                  {durum?.iptal_istendi ? <Spinner boyut={16} /> : <IkonIptal />}
                </button>
              ) : (
                <button type="submit" className={styles.gonderBtn} disabled={!mesaj.trim()} aria-label="Gönder">
                  <IkonGonder />
                </button>
              )}
            </form>
            <div className={styles.secenekler}>
              {takipModu ? (
                <span className={styles.takipNot}>Mevcut projeye ekleme yapılıyor · yeni proje için “Yeni sohbet”</span>
              ) : (
                <>
                  <button type="button" className={`${styles.toggle} ${tasarim ? styles.toggleAcik : ""}`} onClick={() => setTasarim((v) => !v)}>Tasarım</button>
                  <button type="button" className={`${styles.toggle} ${proje ? styles.toggleAcik : ""}`} onClick={() => setProje((v) => !v)}>Proje</button>
                  <button type="button" className={`${styles.toggle} ${docker ? styles.toggleAcik : ""}`} onClick={() => setDocker((v) => !v)}>Docker</button>
                </>
              )}
            </div>
          </div>
        </main>
      </div>

      {/* Değişiklikler modalı */}
      {degisiklik !== null && (
        <div className={styles.modalSar} role="dialog" aria-label="Değişiklikler" onClick={() => setDegisiklik(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalUst}>
              <strong>Son değişiklikler (git diff)</strong>
              <button className={styles.modalKapat} onClick={() => setDegisiklik(null)} aria-label="Kapat"><IkonIptal /></button>
            </div>
            <pre className={styles.diff}>{degisiklik || "(değişiklik yok)"}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
