import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans, IBM_Plex_Serif } from "next/font/google";
import "katex/dist/katex.min.css";
import "./globals.css";

// One type family (IBM Plex), two of its own sub-faces: Serif for the
// wordmark/headings -- an editorial, lab-manual register that most
// SaaS sign-in screens never touch -- Sans for everything functional
// (body copy, buttons, form labels). Self-hosted by Next at build time,
// no runtime request to Google.
const plexSerif = IBM_Plex_Serif({
  subsets: ["latin"],
  weight: ["500", "600"],
  variable: "--font-serif",
  display: "swap",
});
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Catalyst",
  description: "Chemistry lab learning support for BACHY105",
};

// Phones: fit the device width, extend under notches (the composer pads for the
// safe area), and let the on-screen keyboard shrink the page so the composer
// stays visible instead of being covered.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f5f1" },
    { media: "(prefers-color-scheme: dark)", color: "#131416" },
  ],
};

// Runs before React hydrates, so a saved choice applies before first paint.
// With no saved choice the device setting decides (globals.css
// prefers-color-scheme), so nothing flashes either way.
const themeInitScript = `
(function () {
  try {
    var saved = localStorage.getItem("labtutor:theme");
    if (saved === "light" || saved === "dark") document.documentElement.setAttribute("data-theme", saved);
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className={`${plexSans.variable} ${plexSerif.variable}`}>{children}</body>
    </html>
  );
}
