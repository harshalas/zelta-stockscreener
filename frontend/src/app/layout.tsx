import type { Metadata, Viewport } from "next";
import "./globals.css";

// Deliberately no next/font/google here. Pulling Geist from Google Fonts at
// build time makes every build (including CI) depend on reaching Google's
// CDN, and gains nothing over the OS's own monospace stack for a
// terminal-styled dashboard like this one -- Tailwind's `font-mono` already
// resolves to ui-monospace/Menlo/Consolas/SF Mono, which renders instantly
// with zero extra network request on every device this app targets,
// including the phone this is built for.

export const metadata: Metadata = {
  title: "Zelta - Stock Screener",
  description:
    "Deterministic technical and news-sentiment stock analysis -- no LLM calls at request time. Installable to your phone home screen.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Zelta",
  },
  icons: {
    // iOS ignores manifest.json icons for "Add to Home Screen" -- it only
    // reads this link tag, so it's listed explicitly here too.
    apple: "/icons/icon-192.png",
    icon: "/icons/icon-512.png",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  themeColor: "#0d0f14",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        {children}
        <script
          // Registers the app-shell service worker so the page is
          // installable and opens instantly on repeat visits. Inlined
          // (rather than a separate component) so it runs with no
          // dependency on client-side React hydration timing.
          dangerouslySetInnerHTML={{
            __html: `
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', function () {
                  navigator.serviceWorker.register('/sw.js').catch(function () {});
                });
              }
            `,
          }}
        />
      </body>
    </html>
  );
}
