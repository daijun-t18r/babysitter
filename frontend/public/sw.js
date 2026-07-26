// Midnight Companion service worker — the 3am promise.
//
// Hand-rolled (no next-pwa): precaches /sos and the PWA shell on install so
// the SOS calming script — with its bundled emergency numbers — keeps working
// with no network. Strategy:
//   - /sos (HTML + RSC payloads): network-first, cached fallback
//   - precached shell + /_next/static/* (immutable hashed chunks): cache-first
//   - /api/*, /auth*, non-GET, cross-origin: NEVER intercepted, NEVER cached
//
// Bump CACHE_NAME whenever the precache list or a strategy changes — activate
// deletes every other cache version.

const CACHE_NAME = "mc-v1";

// Cached at install. /sos's hashed JS chunks are not enumerable here; the
// cache-first /_next/static/* handler captures them on the first online visit.
const PRECACHE_URLS = [
  "/sos",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        cache.addAll(
          PRECACHE_URLS.map((url) => new Request(url, { cache: "reload" })),
        ),
      )
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

/** Immutable build assets + the precached shell files. */
function isCacheFirst(url) {
  return (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/icons/") ||
    url.pathname === "/manifest.webmanifest"
  );
}

/**
 * Requests the worker must never touch: API calls, auth routes, non-GET,
 * cross-origin. They fall through to the network untouched and are never
 * written to any cache.
 */
function mustBypass(request, url) {
  if (request.method !== "GET") return true;
  if (url.origin !== self.location.origin) return true;
  if (url.pathname.startsWith("/api/")) return true;
  if (url.pathname === "/auth" || url.pathname.startsWith("/auth/")) return true;
  return false;
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (mustBypass(event.request, url)) return;

  // /sos — network-first so the copy stays fresh, cached fallback so it always
  // loads with no signal. Covers hard navigations and Next's RSC payload
  // fetches alike; the Vary header on Next responses keeps HTML and RSC
  // entries from answering each other's requests. When an offline client-side
  // transition fails, Next falls back to a hard navigation, which lands here
  // and is served the precached HTML.
  if (url.pathname === "/sos") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() =>
          caches
            .match(event.request)
            .then((cached) => cached ?? caches.match("/sos")),
        ),
    );
    return;
  }

  // Hashed build assets are immutable — cache-first, populated on first fetch.
  if (isCacheFirst(url)) {
    event.respondWith(
      caches.match(event.request).then(
        (cached) =>
          cached ??
          fetch(event.request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches
                .open(CACHE_NAME)
                .then((cache) => cache.put(event.request, copy));
            }
            return response;
          }),
      ),
    );
  }

  // Everything else (chat, history, settings, …) is untouched: straight to the
  // network, never cached — those pages carry per-user data.
});
