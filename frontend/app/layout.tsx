import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Serif } from "next/font/google";
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
  title: "LabTutor",
  description: "Chemistry lab learning support for BACHY105",
};

// Runs before React hydrates, so a saved "light" preference (or dark,
// the default) applies before first paint -- without this, the page
// would flash dark-then-light for anyone who chose light mode.
const themeInitScript = `
(function () {
  try {
    var saved = localStorage.getItem("labtutor:theme");
    if (saved === "light") document.documentElement.setAttribute("data-theme", "light");
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className={`${plexSans.variable} ${plexSerif.variable}`}>{children}</body>
    </html>
  );
}
