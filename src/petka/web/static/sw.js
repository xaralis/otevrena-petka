// The portal's service worker: only the notifications of Můj přehled (petka.ulice.push). It
// caches nothing; the pages work the same with it or without it.
self.addEventListener("push", (e) => {
  let m = {};
  try { m = e.data ? e.data.json() : {}; } catch { m = { title: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(m.title || "Otevřená Pětka", {
    body: m.body || "", tag: m.tag, data: { url: m.url || "/muj-prehled" },
    icon: "/static/icons/icon-192.png", badge: "/static/icons/icon-192.png", lang: "cs",
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data && e.notification.data.url || "/muj-prehled";
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    const same = list.find((c) => c.url === url);
    return same ? same.focus() : clients.openWindow(url);
  }));
});

// the browser renewed the subscription by itself: tell the portal the new address, same choice
self.addEventListener("pushsubscriptionchange", (e) => {
  e.waitUntil((async () => {
    const old = e.oldSubscription, sub = e.newSubscription;
    if (!old || !sub) return;
    await fetch("/muj-prehled/odber/obnovit", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old: old.endpoint, old_auth: old.toJSON().keys.auth, subscription: sub.toJSON() }) });
  })());
});
