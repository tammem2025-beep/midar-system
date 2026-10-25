/* M — Digital Business Management PWA shell cache — 0.21.0 */
const CACHE='m-shell-v0210';
const SHELL_ASSETS=[
  '/',
  '/midar-ui.css?v=0.21.0',
  '/settings-enhanced.js?v=0.21.0',
  '/app.js?v=0.21.0',
  '/command-center.js?v=0.21.0',
  '/brand-mark.svg',
  '/brand-m-mark.svg',
  '/brand-lockup.svg',
  '/manifest.webmanifest',
  '/icon.svg',
  '/icon-192.png',
  '/icon-512.png',
  '/apple-touch-icon.png',
  '/favicon.ico'
];
self.addEventListener('install',event=>event.waitUntil((async()=>{
  const cache=await caches.open(CACHE);
  await cache.addAll(SHELL_ASSETS);
  await self.skipWaiting();
})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  const keys=await caches.keys();
  await Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)));
  await self.clients.claim();
})()));
self.addEventListener('fetch',event=>{
  const request=event.request;
  const url=new URL(request.url);
  if(url.origin!==location.origin||url.pathname.startsWith('/api/')||request.method!=='GET')return;
  event.respondWith(fetch(request).then(response=>{
    if(response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(request,copy));}
    return response;
  }).catch(()=>caches.match(request).then(cached=>cached||caches.match(url.pathname))));
});
