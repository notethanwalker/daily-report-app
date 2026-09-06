const CACHE_NAME = "daily-report-shell-v2";
const APP_SHELL = ["/", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  event.respondWith(fetch(event.request).then((response) => {
    const copy = response.clone();
    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request).then((cached) => cached || caches.match("/"))));
});

self.addEventListener("push", (event) => {
  let payload={title:"Daily Report alert",body:"A configured market condition was triggered.",url:"/?tab=Alerts",tag:"daily-report-alert"};
  try { payload={...payload,...event.data.json()}; } catch (_) { if(event.data) payload.body=event.data.text(); }
  event.waitUntil(self.registration.showNotification(payload.title,{
    body:payload.body,
    icon:"/icon.svg",
    badge:"/icon.svg",
    tag:payload.tag||"daily-report-alert",
    renotify:true,
    data:{url:payload.url||"/?tab=Alerts",alert_id:payload.alert_id||null},
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url=(event.notification.data&&event.notification.data.url)||"/?tab=Alerts";
  event.waitUntil(self.clients.matchAll({type:"window",includeUncontrolled:true}).then((clients)=>{
    for(const client of clients){if("focus" in client){client.navigate(url);return client.focus();}}
    if(self.clients.openWindow)return self.clients.openWindow(url);
  }));
});
