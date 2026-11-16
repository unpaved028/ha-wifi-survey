// Service Worker: App-Gerüst offline vorhalten, immer zuerst das Netz fragen (keine veralteten Stände).
// Pfade relativ zum Geltungsbereich: die Oberfläche läuft auch unter einem Unterpfad (Ingress von Home Assistant).
const CACHE = 'wifi-survey-v10';
const SHELL = ['./', 'index.html', 'css/app.css', 'js/app.js', 'js/api.js', 'js/geom.js', 'js/viewport.js',
  'js/plans.js', 'js/floor.js', 'js/align.js', 'js/evaluate.js', 'js/survey.js', 'js/locate.js', 'js/start.js',
  'manifest.webmanifest',
  'icons/icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  const scope = new URL(self.registration.scope);
  const rel = url.pathname.startsWith(scope.pathname) ? url.pathname.slice(scope.pathname.length) : null;
  if (e.request.method !== 'GET' || url.origin !== scope.origin || rel === null
      || rel.startsWith('api/') || rel.startsWith('app/')) return;
  e.respondWith(fetch(e.request).then((res) => {
    const copy = res.clone();
    caches.open(CACHE).then((c) => c.put(e.request, copy));
    return res;
  }).catch(() => caches.match(e.request)));
});
