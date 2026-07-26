"use client";

import { useEffect } from "react";

/**
 * Registers the offline service worker (public/sw.js) so /sos keeps working
 * with no network. Production builds on supporting browsers only — everywhere
 * else (next dev, old Safari, SSR) this is a silent no-op.
 */
export function RegisterServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Offline cache is best-effort; the app works without it.
    });
  }, []);
  return null;
}
