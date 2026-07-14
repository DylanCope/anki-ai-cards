import type { Metadata, Viewport } from "next";
import { Inter, Noto_Sans_JP } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { ThemeProvider } from "@/app/components/ThemeProvider";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const notoSansJP = Noto_Sans_JP({
  variable: "--font-noto-sans-jp",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Anjo - Anki Assistant",
  description: "Create Anki flashcards with ease.",
};

// Without this, mobile browsers fall back to a desktop-width virtual
// viewport (~980px) and scale the page down to fit, then re-zoom/pan as
// layout shifts happen (e.g. the history-load auto-scroll) — this pins the
// viewport to the device's actual width at 1:1 scale.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Without this, some mobile browsers overlay the on-screen keyboard on
  // top of the page instead of shrinking the layout viewport, so a
  // `h-dvh`-based fixed-composer layout like this app's doesn't reliably
  // end up positioned above the keyboard.
  interactiveWidget: "resizes-content",
};

// Sets the `dark` class before hydration so the persisted theme choice
// applies on first paint instead of flashing the OS-default theme while
// ThemeProvider's own effect catches up.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = window.localStorage.getItem("anki-ai-cards-theme");
    var dark = stored ? stored === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.classList.toggle("dark", dark);
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${notoSansJP.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="flex h-dvh flex-col overflow-hidden">
        <Script
          id="theme-init"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }}
        />
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
