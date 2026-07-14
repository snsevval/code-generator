"use client";

// Faz 3 — Orkestratör arayüzü: görev/proje ver, ajanların ilerleyişini canlı izle.

import { useCallback, useEffect, useRef, useState } from "react";
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

type Durum = {
  calisiyor: boolean;
  gorev: string | null;
  log: string[];
  hata: string | null;
  sonuc: Sonuc | null;
  onay_bekleyen: { id: number; gorev: string } | null;
};

type Saglik = { api: boolean; proxy: boolean };

// Log satırındaki ajan etiketine göre renk sınıfı
function satirSinifi(satir: string): string {
  if (satir.includes("[planner]")) return styles.planner;
  if (satir.includes("[codegen]")) return styles.codegen;
  if (satir.includes("[validator]")) return styles.validator;
  if (satir.includes("[debugger]")) return styles.debuggerAjan;
  if (satir.includes("[reviewer]")) return styles.reviewer;
  if (satir.includes("[decomposer]") || satir.includes("[proje]")) return styles.proje;
  if (satir.includes("[orkestratör]")) return styles.orkestrator;
  return "";
}

// --- SVG simgeler (emoji yerine; tutarlı 16px çizgi seti) ---

const Spinner = () => (
  <svg className={styles.spinner} width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
    <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
  </svg>
);

const IkonBasarili = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="10" fill="var(--aksan)" fillOpacity="0.15" />
    <path d="m8 12.5 2.5 2.5L16 9.5" stroke="var(--aksan)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const IkonBasarisiz = () => (
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

function AltGorevSatiri({ alt }: { alt: AltGorev }) {
  const ikon =
    alt.durum === "basarili" ? <IkonBasarili /> : alt.durum === "basarisiz" ? <IkonBasarisiz /> : <IkonBekliyor />;
  const etiket =
    alt.durum === "basarili" ? "tamamlandı" : alt.durum === "basarisiz" ? "başarısız" : "bekliyor";
  return (
    <li className={styles.altGorev} data-durum={alt.durum}>
      {ikon}
      <span className={styles.altGorevMetin}>
        {alt.id}. {alt.gorev}
      </span>
      <span className={styles.altGorevEtiket}>{etiket}</span>
    </li>
  );
}

export default function Anasayfa() {
  const [gorev, setGorev] = useState("");
  const [model, setModel] = useState("");
  const [docker, setDocker] = useState(false);
  const [proje, setProje] = useState(false);
  const [onayli, setOnayli] = useState(false);
  const [durum, setDurum] = useState<Durum | null>(null);
  const [gonderimHatasi, setGonderimHatasi] = useState<string | null>(null);
  const [saglik, setSaglik] = useState<Saglik | null>(null);
  const logSonu = useRef<HTMLDivElement>(null);

  const durumuGetir = useCallback(async () => {
    try {
      const y = await fetch(`${API}/api/durum`);
      setDurum(await y.json());
    } catch {
      setDurum(null); // API kapalı
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

  async function onayGonder(devam: boolean) {
    try {
      await fetch(`${API}/api/onay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ devam }),
      });
      await durumuGetir();
    } catch {
      // durum yoklaması zaten sürüyor; geçici hata yut
    }
  }

  async function gorevBaslat(e: React.FormEvent) {
    e.preventDefault();
    setGonderimHatasi(null);
    try {
      const y = await fetch(`${API}/api/gorev`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gorev, model: model || null, docker, proje, onayli: proje && onayli }),
      });
      if (!y.ok) {
        const veri = await y.json().catch(() => null);
        throw new Error(veri?.detail ?? `HTTP ${y.status}`);
      }
      await durumuGetir();
    } catch (err) {
      setGonderimHatasi(err instanceof Error ? err.message : String(err));
    }
  }

  const rozet = (aktif: boolean | undefined, ad: string) => (
    <span className={`${styles.rozet} ${aktif ? styles.rozetIyi : styles.rozetKotu}`}>
      <span className={styles.rozetNokta} aria-hidden />
      {ad}: {aktif ? "açık" : "kapalı"}
    </span>
  );

  return (
    <main className={styles.ana}>
      <header className={styles.baslik}>
        <h1>Kod Üretim Orkestratörü</h1>
        <div className={styles.rozetler}>
          {rozet(saglik?.api, "API")}
          {rozet(saglik?.proxy, "Proxy")}
        </div>
      </header>

      <form onSubmit={gorevBaslat} className={styles.form}>
        <label className={styles.alanEtiketi} htmlFor="gorev">
          Görev {proje && <em>(proje modu: hedef alt görevlere bölünür)</em>}
        </label>
        <textarea
          id="gorev"
          value={gorev}
          onChange={(e) => setGorev(e.target.value)}
          placeholder={
            proje
              ? "Büyük hedefi yaz… (örn. notları JSON'da saklayan modül + CLI + pytest testleri)"
              : "Görevi yaz… (örn. n'inci fibonacci sayısını yazan fib.py, pytest testleriyle)"
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
          <label className={styles.onayKutusu}>
            <input type="checkbox" checked={proje} onChange={(e) => setProje(e.target.checked)} />
            Proje modu
          </label>
          {proje && (
            <label className={styles.onayKutusu}>
              <input type="checkbox" checked={onayli} onChange={(e) => setOnayli(e.target.checked)} />
              Adım adım onay
            </label>
          )}
          <label className={styles.onayKutusu}>
            <input type="checkbox" checked={docker} onChange={(e) => setDocker(e.target.checked)} />
            Docker sandbox
          </label>
          <button type="submit" disabled={durum?.calisiyor ?? false}>
            {durum?.calisiyor ? (
              <>
                <Spinner /> Çalışıyor…
              </>
            ) : (
              "Başlat"
            )}
          </button>
        </div>
        {gonderimHatasi && (
          <p className={styles.hata} role="alert">
            Hata: {gonderimHatasi}
          </p>
        )}
      </form>

      {durum?.gorev && (
        <section className={styles.panel}>
          <h2 className={styles.gorevBasligi}>
            {durum.calisiyor && <Spinner />}
            <span>{durum.gorev}</span>
          </h2>

          {durum.sonuc?.alt_gorevler && (
            <ul className={styles.altGorevler} aria-label="Alt görevler">
              {durum.sonuc.alt_gorevler.map((alt) => (
                <AltGorevSatiri key={alt.id} alt={alt} />
              ))}
            </ul>
          )}

          {durum.onay_bekleyen && (
            <div className={styles.onayPaneli} role="alertdialog" aria-label="Onay bekleniyor">
              <p>
                <strong>Alt görev {durum.onay_bekleyen.id} tamamlandı.</strong>{" "}
                {durum.onay_bekleyen.gorev}
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

          <div className={styles.log} aria-live="polite">
            {durum.log.map((satir, i) => (
              <div key={i} className={satirSinifi(satir)}>
                {satir}
              </div>
            ))}
            {durum.calisiyor && <div className={styles.imlec}>▋</div>}
            <div ref={logSonu} />
          </div>

          {durum.hata && (
            <p className={styles.hata} role="alert">
              Görev hatası: {durum.hata}
            </p>
          )}

          {durum.sonuc && (
            <div className={styles.sonuc}>
              <p className={styles.sonucOzeti}>
                {durum.sonuc.dogrulama_gecti ? <IkonBasarili /> : <IkonBasarisiz />}
                <strong className={durum.sonuc.dogrulama_gecti ? styles.gecti : styles.kaldi}>
                  {durum.sonuc.dogrulama_gecti ? "DOĞRULAMA GEÇTİ" : "DOĞRULAMA KALDI"}
                </strong>
                {!durum.sonuc.proje && <span> · Debug turu: {durum.sonuc.debug_turu}</span>}
                {durum.sonuc.proje && durum.sonuc.entegrasyon && (
                  <span> · Entegrasyon: {durum.sonuc.entegrasyon}</span>
                )}
              </p>
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
            </div>
          )}
        </section>
      )}

      {!durum && (
        <p className={styles.bilgi}>
          API kapalı görünüyor. Başlatmak için:{" "}
          <code>uv run uvicorn orchestrator.api:app --port 8090</code>
        </p>
      )}
    </main>
  );
}
