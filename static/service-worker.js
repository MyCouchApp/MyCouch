const CACHE = 'mycouch-static-v2.9.17-export-menu';
const ASSETS = [
  '/static/app.css?v=2.9.17-settings-page-mascots',
  '/static/mascots/mycouch-logo.png',
  '/static/pwa-192.png',
  '/static/pwa-512.png'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k.startsWith('mycouch-static-') && k !== CACHE).map(k => caches.delete(k))
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith('/static/')) return;
  event.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(resp => {
      if (resp && resp.ok) {
        const copy = resp.clone();
        caches.open(CACHE).then(cache => cache.put(req, copy));
      }
      return resp;
    }))
  );
});
