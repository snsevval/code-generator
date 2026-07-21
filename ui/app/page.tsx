"use client";

// Hero (landing): referans hero-section'ın bizim ürüne uyarlanmış hali.
// Videolu arka plan (özel JS fade), nav, badge, başlık, ve ÇALIŞAN görev kutusu:
// görev yaz → gönder → /api/gorev başlar → panoya (/panel) geçilir.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import styles from "./hero.module.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8090";
const VIDEO_URL =
  "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260329_050842_be71947f-f16e-4a14-810c-06e83d23ddb5.mp4";
const MAKS_KARAKTER = 3000;
const FADE_MS = 250;
const BITISE_KALA_SN = 0.55;

// --- SVG ikonlar (referanstaki set) ---
const IkonChevron = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IkonYukariOk = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IkonYildiz = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M12 2l2.6 6.9L22 9.3l-5.4 4.7L18.2 21 12 17.3 5.8 21l1.6-7L2 9.3l7.4-.4z" />
  </svg>
);
const IkonSparkle = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M12 2l1.8 5.4L19 9.2l-5.2 1.8L12 16l-1.8-5L5 9.2l5.2-1.8zM19 14l.9 2.6L22 17.5l-2.1.9L19 21l-.9-2.6L16 17.5l2.1-.9z" />
  </svg>
);
const IkonAtac = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M21 8.5 11.5 18a4 4 0 0 1-5.7-5.7l8.5-8.5a2.7 2.7 0 0 1 3.8 3.8l-8.5 8.5a1.3 1.3 0 0 1-1.9-1.9l7.8-7.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IkonMikrofon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
    <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" strokeWidth="1.6" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);
const IkonArama = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6" />
    <path d="m20 20-3-3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

// --- Videolu arka plan: referanstaki özel rAF fade sistemi (CSS transition YOK) ---
function VideoArkaplan() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const fadingOutRef = useRef(false);

  // Mevcut opaklıktan hedefe rAF ile geç; her yeni fade öncekini iptal eder (yarış yok)
  const fade = useCallback((hedef: number, sure: number) => {
    const video = videoRef.current;
    if (!video) return;
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    const baslangic = Number(video.style.opacity || "0");
    const t0 = performance.now();
    const adim = (now: number) => {
      const ilerleme = Math.min((now - t0) / sure, 1);
      video.style.opacity = String(baslangic + (hedef - baslangic) * ilerleme);
      if (ilerleme < 1) {
        rafRef.current = requestAnimationFrame(adim);
      } else {
        rafRef.current = null;
      }
    };
    rafRef.current = requestAnimationFrame(adim);
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.style.opacity = "0";

    const baslat = () => {
      fadingOutRef.current = false;
      fade(1, FADE_MS); // yüklenince/loop başında fade-in
    };
    const zamanGuncelle = () => {
      if (!video.duration) return;
      const kalan = video.duration - video.currentTime;
      if (kalan <= BITISE_KALA_SN && !fadingOutRef.current) {
        fadingOutRef.current = true;
        fade(0, FADE_MS); // bitişe 0.55 sn kala fade-out
      }
    };
    const bitti = () => {
      video.style.opacity = "0";
      setTimeout(() => {
        video.currentTime = 0;
        void video.play();
        fadingOutRef.current = false;
        fade(1, FADE_MS); // 100ms sonra başa sar, oynat, geri fade-in
      }, 100);
    };

    video.addEventListener("loadeddata", baslat);
    video.addEventListener("play", baslat);
    video.addEventListener("timeupdate", zamanGuncelle);
    video.addEventListener("ended", bitti);
    void video.play().catch(() => {});
    return () => {
      video.removeEventListener("loadeddata", baslat);
      video.removeEventListener("play", baslat);
      video.removeEventListener("timeupdate", zamanGuncelle);
      video.removeEventListener("ended", bitti);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [fade]);

  return (
    <div className={styles.videoKatman} aria-hidden>
      <video
        ref={videoRef}
        className={styles.video}
        src={VIDEO_URL}
        muted
        playsInline
        preload="auto"
      />
    </div>
  );
}

export default function Hero() {
  const router = useRouter();
  const [gorev, setGorev] = useState("");
  const [tasarim, setTasarim] = useState(false);
  const [proje, setProje] = useState(false);
  const [docker, setDocker] = useState(false);
  const [gonderiliyor, setGonderiliyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);

  async function gonder() {
    const metin = gorev.trim();
    if (!metin || gonderiliyor) return;
    setGonderiliyor(true);
    setHata(null);
    try {
      const yanit = await fetch(`${API}/api/gorev`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gorev: metin, tasarim, proje, docker }),
      });
      if (!yanit.ok) {
        const veri = await yanit.json().catch(() => null);
        throw new Error(veri?.detail ?? `HTTP ${yanit.status}`);
      }
      router.push("/panel"); // görev başladı → panoda izle
    } catch (err) {
      setHata(err instanceof Error ? err.message : String(err));
      setGonderiliyor(false);
    }
  }

  return (
    <main className={styles.kabuk}>
      <VideoArkaplan />

      {/* Navigasyon */}
      <nav className={styles.nav}>
        <span className={styles.logo}>code-generator</span>
        <ul className={styles.menu}>
          <li>Özellikler</li>
          <li className={styles.menuChevron}>
            Nasıl Çalışır <IkonChevron />
          </li>
          <li>Örnekler</li>
          <li>
            <a href="https://snsevval.github.io/code-generator-doc/" target="_blank" rel="noreferrer">
              Dokümanlar
            </a>
          </li>
          <li>İletişim</li>
        </ul>
        <div className={styles.navButonlar}>
          <a
            className={styles.navSaydam}
            href="https://github.com/snsevval/code-generator"
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </a>
          <button className={styles.navSiyah} onClick={() => router.push("/panel")}>
            Uygulamayı Aç
          </button>
        </div>
      </nav>

      {/* Hero içerik */}
      <section className={styles.icerik}>
        <div className={styles.rozet}>
          <span className={styles.rozetKoyu}>
            <IkonYildiz /> Yeni
          </span>
          <span className={styles.rozetMetin}>Doğal dilden çalışan koda</span>
        </div>

        <h1 className={styles.baslik}>Fikrini çalışan koda dönüştür</h1>

        <p className={styles.altBaslik}>
          Görevini doğal dille anlat; sistem kodu yazsın, test etsin, çalıştırıp
          doğrulasın. Sohbet botu kod metni verir — bu, çalışan bir iş teslim eder.
        </p>

        {/* Görev kutusu (referanstaki search box — bizde ÇALIŞIR) */}
        <div className={styles.kutu}>
          <div className={styles.kutuUst}>
            <span className={styles.kutuUstSol}>
              <IkonSparkle /> Ajanlı kod üretimi
            </span>
            <span className={styles.kutuUstSag}>
              <IkonSparkle /> Nemotron ile çalışır
            </span>
          </div>

          <div className={styles.girisAlani}>
            <textarea
              className={styles.giris}
              value={gorev}
              onChange={(e) => setGorev(e.target.value.slice(0, MAKS_KARAKTER))}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void gonder();
                }
              }}
              placeholder="Ne yapmak istersin? Örn. 'FastAPI ile todo uygulaması yap'"
              rows={1}
            />
            <button
              className={styles.gonderBtn}
              onClick={() => void gonder()}
              disabled={!gorev.trim() || gonderiliyor}
              aria-label="Görevi gönder"
            >
              <IkonYukariOk />
            </button>
          </div>

          <div className={styles.kutuAlt}>
            <div className={styles.eylemler}>
              <button
                className={`${styles.eylem} ${tasarim ? styles.eylemAktif : ""}`}
                onClick={() => setTasarim((v) => !v)}
              >
                <IkonSparkle /> Tasarım
              </button>
              <button
                className={`${styles.eylem} ${proje ? styles.eylemAktif : ""}`}
                onClick={() => setProje((v) => !v)}
              >
                <IkonAtac /> Proje
              </button>
              <button
                className={`${styles.eylem} ${docker ? styles.eylemAktif : ""}`}
                onClick={() => setDocker((v) => !v)}
              >
                <IkonMikrofon /> Docker
              </button>
            </div>
            <span className={styles.sayac}>
              {gorev.length.toLocaleString("tr")}/{MAKS_KARAKTER.toLocaleString("tr")}
            </span>
          </div>
        </div>

        {gonderiliyor && <p className={styles.durumNot}>Görev başlatılıyor, panoya geçiliyor…</p>}
        {hata && <p className={styles.hataNot}>Gönderilemedi: {hata}</p>}
      </section>
    </main>
  );
}
