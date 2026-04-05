const CACHE_NAME = "copper-town-v2";
const SHELL_FILES = ["/", "/manifest.json", "/css/style.css", "/js/store.js", "/js/api.js", "/js/app.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(SHELL_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Network-first for API calls
  if (url.pathname.startsWith("/api/") || url.pathname === "/health") {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  // Cache-first for shell files
  e.respondWith(
    caches.match(e.request).then((cached) => cached || fetch(e.request))
  );
});
