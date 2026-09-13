/** @type {import('next').NextConfig} */
const nextConfig = {
  // `output: 'export'` was here to feed Capacitor's Android WebView bundle
  // (webDir: 'out'). That's gone -- this deploys as a normal Next.js app on
  // Vercel now, and mobile access is a responsive, installable PWA instead
  // (see public/manifest.json), which needs the regular Next.js runtime,
  // not a static export.
};

module.exports = nextConfig;
