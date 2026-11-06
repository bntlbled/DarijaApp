// Minimal service worker: lets Android install the app so it shows up in the Share sheet.
// Everything goes straight to the network; nothing is cached.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
