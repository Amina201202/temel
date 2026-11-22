// Temel service worker: tetbiq kimi qurasdirmaq ve internet olmayanda esas ekrani gostermek ucun
const CACHE = "temel-v7";
const SHELL = ["./", "index.html", "style.css", "app.js", "theme.js", "manifest.json",
  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  // kohne cache-leri silirik
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // API sorgularina toxunmuruq, yalniz /app altindaki fayllar
  if (e.request.method !== "GET" || url.origin !== location.origin || !url.pathname.startsWith("/app/")) return;
  // evvelce internet (kod tez-tez yenilenir), alinmasa cache
  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        const copy = resp.clone();
        if (resp.ok) caches.open(CACHE).then((c) => c.put(e.request, copy));
        return resp;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true }).then((r) => r || caches.match("index.html")))
  );
});
