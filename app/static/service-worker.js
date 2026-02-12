const CACHE = "qr-order-cache-v1";
const ASSETS = [
    "/static/styles.css",
    "/static/app.js",
    "/static/staff.js",
    "/static/manifest.json"
];

self.addEventListener("install", (e) => {
    e.waitUntil(
        caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (e) => {
    e.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (e) => {
    const req = e.request;
    if (req.method !== "GET") return;
    e.respondWith(
        caches.match(req).then(cached => cached || fetch(req).catch(() => cached))
    );
});
