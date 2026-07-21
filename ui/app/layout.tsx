import type { Metadata } from "next";
import {
  Fira_Code,
  Fustat,
  Inter,
  Noto_Sans,
  Schibsted_Grotesk,
} from "next/font/google";
import "./globals.css";

// Pano fontları (mevcut — dokunulmadı)
const inter = Inter({
  variable: "--font-govde",
  subsets: ["latin", "latin-ext"],
});

const firaCode = Fira_Code({
  variable: "--font-kod",
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600"],
});

// Hero (landing) fontları — referans birebir
const fustat = Fustat({
  variable: "--font-fustat",
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600", "700"],
});

const schibsted = Schibsted_Grotesk({
  variable: "--font-schibsted",
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600", "700"],
});

const notoSans = Noto_Sans({
  variable: "--font-noto",
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "CodeG",
  description: "Agentic kod üretim döngüsünü izleme arayüzü",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="tr"
      className={`${inter.variable} ${firaCode.variable} ${fustat.variable} ${schibsted.variable} ${notoSans.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
