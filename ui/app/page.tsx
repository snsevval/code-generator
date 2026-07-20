"use client";

// Orkestratör panosu: görev ver, ajan akışını ve kaynak kullanımını canlı izle.
// Tüm göstergeler gerçek veriden türetilir (API durumu + canlı log satırları).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import styles from "./page.module.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8090";

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

const AJANLAR = [
  { ad: "planner", etiket: "Planner" },
  { ad: "codegen", etiket: "Codegen" },
  { ad: "validator", etiket: "Validator" },
  { ad: "debugger", etiket: "Debugger" },
  { ad: "reviewer", etiket: "Reviewer" },
] as const;

type AsamaDurumu = "bekliyor" | "calisiyor" | "tamam";

// Canlı logdan ajan akış durumunu türet
function asamaDurumlari(log: string[]): Record<string, AsamaDurumu> {
  const durum: Record<string, AsamaDurumu> = {};
  for (const a of AJANLAR) durum[a.ad] = "bekliyor";
  for (const satir of log) {
    for (const a of AJANLAR) {
      if (satir.includes(`[${a.ad}] başlıyor`)) durum[a.ad] = "calisiyor";
      if (satir.includes(`[${a.ad}] bitti`)) durum[a.ad] = "tamam";
    }
  }
  return durum;
}

type Dosya = { ad: string; boyut: number };

function boyutBicimle(bayt: number): string {
  if (bayt >= 1024 * 1024) return `${(bayt / 1024 / 1024).toFixed(1)} MB`;
  if (bayt >= 1024) return `${(bayt / 1024).toFixed(1)} KB`;
  return `${bayt} B`;
}

function satirSinifi(satir: string): string {
  if (satir.includes("[planner]")) return styles.planner;
  if (satir.includes("[codegen]")) return styles.codegen;
  if (satir.includes("[validator]")) return styles.validator;
  if (satir.includes("[debugger]")) return styles.debuggerAjan;
  if (satir.includes("[reviewer]")) return styles.reviewer;
  if (satir.includes("[decomposer]") || satir.includes("[proje]")) return styles.proje;
  if (satir.includes("[orkestratör]") || satir.includes("[git]")) return styles.orkestrator;
  return "";
}

function tokenBicimle(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}


// Yalnızca renkleri değiştirir; yerleşim ve davranışlara dokunmaz.
const YUMUSAK_MOR_TEMA = `
  .${styles.kabuk} {
    background: #1f2024 !important;
    color: #f0eef5 !important;
    --mor: #a78bfa;
    --mor-acik: #c4b5fd;
    --indigo: #8f9cf4;
    --basari: #8fc9a8;
    --tehlike: #e3a0ad;
    --kenar-belirgin: #555762;
  }

  .${styles.marka} h1 {
    color: #b79cff !important;
  }

  .${styles.marka} p,
  .${styles.karakterSayaci},
  .${styles.akisDurum},
  .${styles.altGorevEtiket},
  .${styles.dosyaBoyut},
  .${styles.kaynakIkincil},
  .${styles.ozet} dt {
    color: #aaa7b2 !important;
  }

  .${styles.kart},
  .${styles.onayPaneli},
  .${styles.bilgi} {
    background: #292a30 !important;
    border-color: #3d3f48 !important;
  }

  .${styles.kart} h2,
  .${styles.akisAd},
  .${styles.altGorevMetin},
  .${styles.ozet} dd,
  .${styles.kaynakListe},
  .${styles.dosyaLink} {
    color: #eceaf1 !important;
  }

  .${styles.kart} textarea,
  .${styles.kart} select,
  .${styles.log},
  .${styles.kart} details,
  .${styles.dosyaListe} li,
  .${styles.altGorev} {
    background: #24252a !important;
    border-color: #3f414a !important;
    color: #eceaf1 !important;
  }

  .${styles.kart} textarea::placeholder {
    color: #85828d !important;
  }

  .${styles.kart} textarea:focus,
  .${styles.kart} select:focus {
    border-color: #9d83e8 !important;
    outline-color: #9d83e8 !important;
  }

  .${styles.kart} button,
  .${styles.onayButonlari} button,
  .${styles.onizleBaslat} {
    background: #9075d8 !important;
    border-color: #a98ee8 !important;
    color: #ffffff !important;
  }

  .${styles.kart} button:hover,
  .${styles.onayButonlari} button:hover,
  .${styles.onizleBaslat}:hover {
    background: #9e84e2 !important;
  }

  .${styles.anahtar},
  .${styles.rozet},
  .${styles.durumEtiketi},
  .${styles.canliEtiket},
  .${styles.indirDugmesi},
  .${styles.onizleDurdur} {
    background: #303139 !important;
    border-color: #494b55 !important;
    color: #c9c6d0 !important;
  }

  .${styles.anahtarAcik},
  .${styles.durumAktif},
  .${styles.canliEtiket} {
    background: #3a334d !important;
    border-color: #735fa4 !important;
    color: #cbbcf2 !important;
  }

  .${styles.rozetIyi},
  .${styles.durumIyi},
  .${styles.gecti},
  .${styles.onizleAcik} {
    color: #9bd3b4 !important;
  }

  .${styles.rozetKotu},
  .${styles.durumKotu},
  .${styles.kaldi},
  .${styles.hata},
  .${styles.durdurButonu} {
    color: #e5a3af !important;
  }

  .${styles.durdurButonu} {
    background: #493238 !important;
    border-color: #744951 !important;
  }

  .${styles.akisAdimi} {
    border-color: #3f414a !important;
  }

  .${styles.akisNumara} {
    background: #303139 !important;
    border-color: #4a4c56 !important;
    color: #bbb7c5 !important;
  }

  .${styles.halkaIc} {
    background: #292a30 !important;
  }

  .${styles.planner} { color: #9fbfe0 !important; }
  .${styles.codegen} { color: #c5a7eb !important; }
  .${styles.validator} { color: #9fcbb6 !important; }
  .${styles.debuggerAjan} { color: #dfb08f !important; }
  .${styles.reviewer} { color: #b9acd9 !important; }
  .${styles.proje} { color: #aab7d7 !important; }
  .${styles.orkestrator} { color: #d1a9c1 !important; }
  .${styles.imlec} { color: #b79cff !important; }
`;

// --- SVG simgeler (tek çizgi ailesi, 16px) ---

const Spinner = ({ boyut = 16 }: { boyut?: number }) => (
  <svg className={styles.spinner} width={boyut} height={boyut} viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
    <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
  </svg>
);

const IkonTamam = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="10" fill="var(--basari)" fillOpacity="0.15" />
    <path d="m8 12.5 2.5 2.5L16 9.5" stroke="var(--basari)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const IkonHata = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="10" fill="var(--tehlike)" fillOpacity="0.15" />
    <path d="m9 9 6 6M15 9l-6 6" stroke="var(--tehlike)" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

const IkonBekliyor = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="9" stroke="var(--kenar-belirgin)" strokeWidth="2" strokeDasharray="3 3" />
  </svg>
);

const IkonDosya = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path
      d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"
      stroke="var(--mor-acik)"
      strokeWidth="1.7"
      strokeLinejoin="round"
    />
    <path d="M14 3v5h5" stroke="var(--mor-acik)" strokeWidth="1.7" strokeLinejoin="round" />
  </svg>
);

export default function Anasayfa() {
  const [gorev, setGorev] = useState("");
  const [model, setModel] = useState("");
  const [docker, setDocker] = useState(false);
  const [proje, setProje] = useState(false);
  const [onayli, setOnayli] = useState(false);
  const [tasarim, setTasarim] = useState(false);
  const [durum, setDurum] = useState<Durum | null>(null);
  const [gonderimHatasi, setGonderimHatasi] = useState<string | null>(null);
  const [saglik, setSaglik] = useState<Saglik | null>(null);
  const logSonu = useRef<HTMLDivElement>(null);

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
        const y = await fetch(`${API}/api/saglik`);
        setSaglik(await y.json());
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
    logSonu.current?.scrollIntoView({ behavior: "smooth" });
  }, [durum?.log.length]);

  const asamalar = useMemo(() => asamaDurumlari(durum?.log ?? []), [durum?.log]);

  // Çıktı dosyaları: görev klasörünün gerçek içeriği (API'den)
  const [dosyalar, setDosyalar] = useState<Dosya[]>([]);
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

  async function onayGonder(devam: boolean) {
    try {
      await fetch(`${API}/api/onay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ devam }),
      });
      await durumuGetir();
    } catch {
      /* durum yoklaması sürüyor */
    }
  }

  const [onizlemeHatasi, setOnizlemeHatasi] = useState<string | null>(null);
  const [onizlemeYukleniyor, setOnizlemeYukleniyor] = useState(false);

  // package.json'lı proje mi? (Vite/dev-server gerektirir)
  const projeKlasoru = useMemo(() => {
    const pkg = dosyalar.find((d) => d.ad.endsWith("package.json"));
    if (!pkg) return null;
    const dizin = pkg.ad.includes("/") ? pkg.ad.slice(0, pkg.ad.lastIndexOf("/")) : "";
    return dizin; // "" = kök, "counter-app" = alt klasör
  }, [dosyalar]);

  async function onizlemeBaslat() {
    if (projeKlasoru === null) return;
    setOnizlemeHatasi(null);
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
      setOnizlemeHatasi(err instanceof Error ? err.message : String(err));
    } finally {
      setOnizlemeYukleniyor(false);
    }
  }

  async function onizlemeDurdur() {
    await fetch(`${API}/api/onizle-durdur`, { method: "POST" }).catch(() => {});
    await durumuGetir();
  }

  // Takip modu: mevcut proje üzerinde yeni istek ("rengi değiştir", "buton ekle"…)
  const [takipIstek, setTakipIstek] = useState("");

  async function istekGonder(metin: string, takip: boolean) {
    setGonderimHatasi(null);
    setOnizlemeHatasi(null);
    if (!takip) setDosyalar([]); // yeni proje: eski dosyalar anında temizlensin
    const y = await fetch(`${API}/api/gorev`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        gorev: metin,
        model: model || null,
        docker,
        proje: takip ? false : proje,
        onayli: !takip && proje && onayli,
        tasarim: takip ? false : tasarim,
        takip,
      }),
    });
    if (!y.ok) {
      const veri = await y.json().catch(() => null);
      throw new Error(veri?.detail ?? `HTTP ${y.status}`);
    }
    await durumuGetir();
  }

  async function gorevBaslat(e: React.FormEvent) {
    e.preventDefault();
    try {
      await istekGonder(gorev, false);
    } catch (err) {
      setGonderimHatasi(err instanceof Error ? err.message : String(err));
    }
  }

  async function takipGonder(e: React.FormEvent) {
    e.preventDefault();
    if (!takipIstek.trim()) return;
    try {
      await istekGonder(takipIstek, true);
      setTakipIstek("");
    } catch (err) {
      setGonderimHatasi(err instanceof Error ? err.message : String(err));
    }
  }

  // Çalışan görevi iptal et (yanlış görev gönderildiğinde yeni projeye geçebilmek için)
  async function iptalEt() {
    try {
      await fetch(`${API}/api/iptal`, { method: "POST" });
      await durumuGetir();
    } catch (err) {
      setGonderimHatasi(err instanceof Error ? err.message : String(err));
    }
  }

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
              ? "Tamamlandı"
              : "Doğrulama kaldı"
            : "Boşta";

  const k = durum?.kullanim;
  const toplamToken = k ? k.girdi + k.cikti : 0;
  const girisAcisi = toplamToken > 0 ? (k!.girdi / toplamToken) * 360 : 0;

  const rozet = (aktif: boolean | undefined, ad: string) => (
    <span className={`${styles.rozet} ${aktif ? styles.rozetIyi : styles.rozetKotu}`}>
      <span className={styles.rozetNokta} aria-hidden />
      {ad}: {aktif ? "bağlı" : "kapalı"}
    </span>
  );

  return (
    <div className={styles.kabuk}>
      <style>{YUMUSAK_MOR_TEMA}</style>
      <header className={styles.baslik}>
        <div className={styles.marka}>
          
          <div>
            
            <p>Doğal dille görev tanımla, ajan döngüsünü canlı izle</p>
          </div>
        </div>
        <div className={styles.rozetler}>
          {rozet(saglik?.api, "API")}
          {rozet(saglik?.proxy, "Proxy")}
        </div>
      </header>

      <div className={styles.izgara}>
        {/* ---- Sol: görev + akış + log ---- */}
        <main className={styles.anaKolon}>
          <form onSubmit={gorevBaslat} className={styles.kart}>
            <div className={styles.kartBaslik}>
              <h2>Görev Oluştur</h2>
              <span className={styles.karakterSayaci}>{gorev.length} karakter</span>
            </div>
            <textarea
              value={gorev}
              onChange={(e) => setGorev(e.target.value)}
              placeholder={
                proje
                  ? "Büyük hedefi yaz… (alt görevlere bölünüp zincir halinde koşulur)"
                  : "Görevi yaz… (örn. sifre_uret.py: güçlü şifre üreten araç, pytest testleriyle)"
              }
              rows={3}
              required
            />
            <div className={styles.formAlt}>
              <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model seçimi">
                <option value="">Varsayılan model (proxy rotası)</option>
                <option value="gemini/gemini-2.5-flash">Gemini 2.5 Flash</option>
                <option value="groq/llama-3.3-70b-versatile">Groq Llama 3.3 70B</option>
              </select>
              <label className={`${styles.anahtar} ${proje ? styles.anahtarAcik : ""}`}>
                <input type="checkbox" checked={proje} onChange={(e) => setProje(e.target.checked)} />
                Proje modu
              </label>
              {proje && (
                <label className={`${styles.anahtar} ${onayli ? styles.anahtarAcik : ""}`}>
                  <input type="checkbox" checked={onayli} onChange={(e) => setOnayli(e.target.checked)} />
                  Adım adım onay
                </label>
              )}
              <label
                className={`${styles.anahtar} ${tasarim ? styles.anahtarAcik : ""}`}
                title="ui-ux-pro-max tasarım sistemi göreve eklenir; HTML çıktıları tarayıcıda açılıp görsel olarak analiz edilir"
              >
                <input type="checkbox" checked={tasarim} onChange={(e) => setTasarim(e.target.checked)} />
                UI görevi
              </label>
              <label className={`${styles.anahtar} ${docker ? styles.anahtarAcik : ""}`}>
                <input type="checkbox" checked={docker} onChange={(e) => setDocker(e.target.checked)} />
                Docker sandbox
              </label>
              <button type="submit" disabled={durum?.calisiyor ?? false}>
                {durum?.calisiyor ? (
                  <>
                    <Spinner /> Çalışıyor…
                  </>
                ) : (
                  <>▶ Başlat</>
                )}
              </button>
              {durum?.calisiyor && (
                <button
                  type="button"
                  onClick={iptalEt}
                  className={styles.durdurButonu}
                  disabled={durum?.iptal_istendi ?? false}
                >
                  {durum?.iptal_istendi ? "Durduruluyor…" : "✕ İptal"}
                </button>
              )}
            </div>
            {gonderimHatasi && (
              <p className={styles.hata} role="alert">
                {gonderimHatasi}
              </p>
            )}
          </form>

          {durum?.gorev && (
            <>
              <section className={styles.kart} aria-label="Orkestrasyon akışı">
                <div className={styles.kartBaslik}>
                  <h2>Orkestrasyon Akışı</h2>
                </div>
                <ol className={styles.akis}>
                  {AJANLAR.map((a, i) => {
                    const d = asamalar[a.ad];
                    return (
                      <li key={a.ad} className={styles.akisAdimi} data-durum={d}>
                        <span className={styles.akisNumara}>
                          {d === "tamam" ? <IkonTamam /> : d === "calisiyor" ? <Spinner /> : i + 1}
                        </span>
                        <span className={styles.akisAd}>{a.etiket}</span>
                        <span className={styles.akisDurum}>
                          {d === "tamam" ? "tamamlandı" : d === "calisiyor" ? "çalışıyor" : "beklemede"}
                        </span>
                      </li>
                    );
                  })}
                </ol>
              </section>

              {durum.onay_bekleyen && (
                <div className={styles.onayPaneli} role="alertdialog" aria-label="Onay bekleniyor">
                  <p>
                    <strong>Alt görev {durum.onay_bekleyen.id} tamamlandı.</strong> {durum.onay_bekleyen.gorev}
                  </p>
                  <div className={styles.onayButonlari}>
                    <button type="button" onClick={() => onayGonder(true)}>
                      Devam et
                    </button>
                    <button type="button" className={styles.durdurButonu} onClick={() => onayGonder(false)}>
                      Durdur
                    </button>
                  </div>
                </div>
              )}

              {durum.sonuc?.alt_gorevler && (
                <section className={styles.kart} aria-label="Alt görevler">
                  <div className={styles.kartBaslik}>
                    <h2>Alt Görevler</h2>
                  </div>
                  <ul className={styles.altGorevler}>
                    {durum.sonuc.alt_gorevler.map((alt) => (
                      <li key={alt.id} className={styles.altGorev} data-durum={alt.durum}>
                        {alt.durum === "basarili" ? <IkonTamam /> : alt.durum === "basarisiz" ? <IkonHata /> : <IkonBekliyor />}
                        <span className={styles.altGorevMetin}>
                          {alt.id}. {alt.gorev}
                        </span>
                        <span className={styles.altGorevEtiket}>
                          {alt.durum === "basarili" ? "tamamlandı" : alt.durum === "basarisiz" ? "başarısız" : "bekliyor"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section className={styles.kart} aria-label="Canlı log">
                <div className={styles.kartBaslik}>
                  <h2>Canlı Log</h2>
                  {durum.calisiyor && (
                    <span className={styles.canliEtiket}>
                      <span className={styles.rozetNokta} aria-hidden /> canlı
                    </span>
                  )}
                </div>
                <div className={styles.log} aria-live="polite">
                  {durum.log.map((satir, i) => (
                    <div key={i} className={satirSinifi(satir)}>
                      {satir}
                    </div>
                  ))}
                  {durum.calisiyor && <div className={styles.imlec}>▋</div>}
                  <div ref={logSonu} />
                </div>
              </section>

              {durum.hata && (
                <p className={styles.hata} role="alert">
                  Görev hatası: {durum.hata}
                </p>
              )}

              {/* Takip: görev bitince aynı proje üzerinde yeni istek ver */}
              {!durum.calisiyor && durum.klasor && (durum.sonuc || durum.hata) && (
                <section className={styles.kart}>
                  <div className={styles.kartBaslik}>
                    <h2>Projeye devam et</h2>
                    <span className={styles.karakterSayaci}>{durum.klasor}</span>
                  </div>
                  {(durum.sohbet?.length ?? 0) > 0 && (
                    <ol style={{ margin: "0 0 10px", paddingLeft: 18, fontSize: 13, opacity: 0.85 }}>
                      {durum.sohbet.map((s, i) => (
                        <li key={i} style={{ marginBottom: 2 }}>
                          {s.basarili ? "✅" : "⚠️"} {s.istek.length > 90 ? s.istek.slice(0, 90) + "…" : s.istek}
                        </li>
                      ))}
                    </ol>
                  )}
                  <form onSubmit={takipGonder} style={{ display: "flex", gap: 8 }}>
                    <input
                      type="text"
                      value={takipIstek}
                      onChange={(e) => setTakipIstek(e.target.value)}
                      placeholder="Değişiklik iste… (örn. arka planı koyu yap, listeye animasyon ekle)"
                      style={{ flex: 1 }}
                    />
                    <button type="submit" disabled={!takipIstek.trim()}>
                      ↻ Uygula
                    </button>
                  </form>
                  <p style={{ margin: "8px 0 0", fontSize: 12, opacity: 0.7 }}>
                    Mevcut dosyalar korunur; yalnızca istenen değişiklik uygulanır ve proje yeniden
                    doğrulanır. Yeni bir projeye başlamak için üstteki formu kullan.
                  </p>
                </section>
              )}

              {durum.sonuc && (durum.sonuc.plan || durum.sonuc.reviewer) && (
                <section className={styles.kart}>
                  <div className={styles.kartBaslik}>
                    <h2>Raporlar</h2>
                  </div>
                  {durum.sonuc.plan && (
                    <details>
                      <summary>Plan</summary>
                      <pre>{durum.sonuc.plan}</pre>
                    </details>
                  )}
                  {durum.sonuc.reviewer && (
                    <details open>
                      <summary>Reviewer raporu</summary>
                      <pre>{durum.sonuc.reviewer}</pre>
                    </details>
                  )}
                </section>
              )}
            </>
          )}

          {!durum && (
            <p className={styles.bilgi}>
              API kapalı görünüyor. Başlatmak için: <code>uv run uvicorn orchestrator.api:app --port 8090</code>
            </p>
          )}
        </main>

        {/* ---- Sağ ray: özet + kaynak + dosyalar ---- */}
        {durum?.gorev && (
          <aside className={styles.ray}>
            <section className={styles.kart} aria-label="Çalıştırma özeti">
              <div className={styles.kartBaslik}>
                <h2>Çalıştırma Özeti</h2>
                <span
                  className={`${styles.durumEtiketi} ${
                    durumEtiketi === "Tamamlandı"
                      ? styles.durumIyi
                      : durumEtiketi === "Çalışıyor" || durumEtiketi === "Onay bekliyor"
                        ? styles.durumAktif
                        : durumEtiketi === "Boşta"
                          ? ""
                          : styles.durumKotu
                  }`}
                >
                  {durumEtiketi}
                </span>
              </div>
              <dl className={styles.ozet}>
                <div>
                  <dt>Klasör</dt>
                  <dd className={styles.kodMetin}>{durum.klasor ?? "—"}</dd>
                </div>
                <div>
                  <dt>Mod</dt>
                  <dd>{durum.sonuc?.proje || durum.log.some((s) => s.includes("[decomposer]")) ? "Proje (zincir)" : "Tek görev"}</dd>
                </div>
                {durum.sonuc && !durum.sonuc.proje && (
                  <div>
                    <dt>Debug turu</dt>
                    <dd>{durum.sonuc.debug_turu}</dd>
                  </div>
                )}
                {durum.sonuc?.proje && durum.sonuc.entegrasyon && (
                  <div>
                    <dt>Entegrasyon</dt>
                    <dd>{durum.sonuc.entegrasyon}</dd>
                  </div>
                )}
                {durum.sonuc && (
                  <div>
                    <dt>Doğrulama</dt>
                    <dd className={durum.sonuc.dogrulama_gecti ? styles.gecti : styles.kaldi}>
                      {durum.sonuc.dogrulama_gecti ? "GEÇTİ" : "KALDI"}
                    </dd>
                  </div>
                )}
              </dl>
            </section>

            {k && k.istek > 0 && (
              <section className={styles.kart} aria-label="Kaynak kullanımı">
                <div className={styles.kartBaslik}>
                  <h2>Kaynak Kullanımı</h2>
                </div>
                <div className={styles.kaynak}>
                  <div
                    className={styles.halka}
                    style={{ background: `conic-gradient(var(--mor) 0deg ${girisAcisi}deg, var(--indigo) ${girisAcisi}deg 360deg)` }}
                    role="img"
                    aria-label={`Toplam ${tokenBicimle(toplamToken)} token`}
                  >
                    <div className={styles.halkaIc}>
                      <strong>{tokenBicimle(toplamToken)}</strong>
                      <span>token</span>
                    </div>
                  </div>
                  <ul className={styles.kaynakListe}>
                    <li>
                      <span className={styles.noktaMor} aria-hidden /> Giriş: {tokenBicimle(k.girdi)}
                    </li>
                    <li>
                      <span className={styles.noktaIndigo} aria-hidden /> Çıkış: {tokenBicimle(k.cikti)}
                    </li>
                    <li className={styles.kaynakIkincil}>İstek: {k.istek}</li>
                  </ul>
                </div>
              </section>
            )}

            {dosyalar.length > 0 && (
              <section className={styles.kart} aria-label="Çıktı dosyaları">
                <div className={styles.kartBaslik}>
                  <h2>Çıktı Dosyaları</h2>
                  <span className={styles.karakterSayaci}>{dosyalar.length}</span>
                </div>

                {projeKlasoru !== null && (
                  <div className={styles.onizlemeSatiri}>
                    {durum.onizleme_url ? (
                      <>
                        <a
                          className={styles.onizleAcik}
                          href={durum.onizleme_url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          ● Canlı: {durum.onizleme_url}
                        </a>
                        <button type="button" className={styles.onizleDurdur} onClick={onizlemeDurdur}>
                          Durdur
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className={styles.onizleBaslat}
                        onClick={onizlemeBaslat}
                        disabled={onizlemeYukleniyor}
                      >
                        {onizlemeYukleniyor ? (
                          <>
                            <Spinner /> Sunucu başlatılıyor…
                          </>
                        ) : (
                          "▶ Canlı Önizle (dev sunucusu)"
                        )}
                      </button>
                    )}
                  </div>
                )}
                {onizlemeHatasi && (
                  <p className={styles.hata} role="alert">
                    Önizleme: {onizlemeHatasi}
                  </p>
                )}
                <ul className={styles.dosyaListe}>
                  {dosyalar.map((d) => (
                    <li key={d.ad}>
                      <IkonDosya />
                      <a
                        className={`${styles.kodMetin} ${styles.dosyaLink}`}
                        href={`${API}/api/dosya?ad=${encodeURIComponent(d.ad)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Kaynağı görüntüle"
                      >
                        {d.ad}
                      </a>
                      <span className={styles.dosyaBoyut}>{boyutBicimle(d.boyut)}</span>
                      {/\.html?$/i.test(d.ad) && (
                        <a
                          className={styles.indirDugmesi}
                          href={
                            durum?.onizleme_backend_url && /(^|\/)index\.html?$/i.test(d.ad)
                              ? durum.onizleme_backend_url
                              : `${API}/onizle/${d.ad.split("/").map(encodeURIComponent).join("/")}`
                          }
                          target="_blank"
                          rel="noopener noreferrer"
                          title={
                            durum?.onizleme_backend_url && /(^|\/)index\.html?$/i.test(d.ad)
                              ? `${d.ad} — canlı backend'e bağlı önizleme`
                              : `${d.ad} sayfasını canlı önizle`
                          }
                          aria-label={`${d.ad} sayfasını önizle`}
                        >
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
                            <path
                              d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinejoin="round"
                            />
                            <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
                          </svg>
                        </a>
                      )}
                      <a
                        className={styles.indirDugmesi}
                        href={`${API}/api/dosya?ad=${encodeURIComponent(d.ad)}&indir=1`}
                        download={d.ad}
                        title={`${d.ad} dosyasını indir`}
                        aria-label={`${d.ad} dosyasını indir`}
                      >
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
                          <path
                            d="M12 4v11m0 0 4-4m-4 4-4-4M5 19h14"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
