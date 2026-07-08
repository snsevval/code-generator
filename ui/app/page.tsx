"use client";

// Faz 3 — Orkestratör arayüzü: görev ver, ajanların ilerleyişini canlı izle.

import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./page.module.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8090";

type Durum = {
  calisiyor: boolean;
  gorev: string | null;
  log: string[];
  hata: string | null;
  sonuc: {
    dogrulama_gecti: boolean;
    debug_turu: number;
    reviewer: string;
    plan: string;
  } | null;
};

type Saglik = { api: boolean; proxy: boolean };

// Log satırındaki ajan etiketine göre renk sınıfı
function satirSinifi(satir: string): string {
  if (satir.includes("[planner]")) return styles.planner;
  if (satir.includes("[codegen]")) return styles.codegen;
  if (satir.includes("[validator]")) return styles.validator;
  if (satir.includes("[debugger]")) return styles.debuggerAjan;
  if (satir.includes("[reviewer]")) return styles.reviewer;
  if (satir.includes("[orkestratör]")) return styles.orkestrator;
  return "";
}

export default function Anasayfa() {
  const [gorev, setGorev] = useState("");
  const [model, setModel] = useState("");
  const [docker, setDocker] = useState(false);
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

  // Sağlık 10 sn'de bir; ilk durum yüklemesi bir kez
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

  // Görev koşarken durumu 1.5 sn'de bir yokla
  useEffect(() => {
    if (!durum?.calisiyor) return;
    const s = setInterval(durumuGetir, 1500);
    return () => clearInterval(s);
  }, [durum?.calisiyor, durumuGetir]);

  // Yeni log satırında en alta kay
  useEffect(() => {
    logSonu.current?.scrollIntoView({ behavior: "smooth" });
  }, [durum?.log.length]);

  async function gorevBaslat(e: React.FormEvent) {
    e.preventDefault();
    setGonderimHatasi(null);
    try {
      const y = await fetch(`${API}/api/gorev`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gorev, model: model || null, docker }),
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
      {ad}: {aktif ? "açık" : "kapalı"}
    </span>
  );

  return (
    <main className={styles.ana}>
      <header className={styles.baslik}>
        <h1>Kod Üretim Orkestratörü</h1>
        <div>
          {rozet(saglik?.api, "API")}
          {rozet(saglik?.proxy, "Proxy")}
        </div>
      </header>

      <form onSubmit={gorevBaslat} className={styles.form}>
        <textarea
          value={gorev}
          onChange={(e) => setGorev(e.target.value)}
          placeholder="Görevi yaz… (örn. n'inci fibonacci sayısını yazan fib.py adında bir CLI aracı yaz, pytest testleriyle)"
          rows={3}
          required
        />
        <div className={styles.formAlt}>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">Varsayılan model</option>
            <option value="gemini/gemini-2.5-flash">Gemini 2.5 Flash</option>
            <option value="groq/llama-3.3-70b-versatile">Groq Llama 3.3 70B</option>
          </select>
          <label className={styles.onayKutusu}>
            <input
              type="checkbox"
              checked={docker}
              onChange={(e) => setDocker(e.target.checked)}
            />
            Docker sandbox
          </label>
          <button type="submit" disabled={durum?.calisiyor ?? false}>
            {durum?.calisiyor ? "Çalışıyor…" : "Görevi Başlat"}
          </button>
        </div>
        {gonderimHatasi && <p className={styles.hata}>Hata: {gonderimHatasi}</p>}
      </form>

      {durum?.gorev && (
        <section className={styles.panel}>
          <h2>
            {durum.calisiyor ? "⏳ " : ""}
            {durum.gorev}
          </h2>
          <div className={styles.log}>
            {durum.log.map((satir, i) => (
              <div key={i} className={satirSinifi(satir)}>
                {satir}
              </div>
            ))}
            {durum.calisiyor && <div className={styles.imlec}>▋</div>}
            <div ref={logSonu} />
          </div>

          {durum.hata && <p className={styles.hata}>Görev hatası: {durum.hata}</p>}

          {durum.sonuc && (
            <div className={styles.sonuc}>
              <p>
                Doğrulama:{" "}
                <strong
                  className={durum.sonuc.dogrulama_gecti ? styles.gecti : styles.kaldi}
                >
                  {durum.sonuc.dogrulama_gecti ? "GEÇTİ" : "KALDI"}
                </strong>
                {" · "}Debug turu: {durum.sonuc.debug_turu}
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
