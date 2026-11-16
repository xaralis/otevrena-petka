// Můj přehled: the form of the page works without this script (it posts back to the page); here it
// is taken over in place. Picking a street adds its token, × drops it, a checkbox changes the
// kinds; each change rewrites the URL, asks nahled.json for the preview, the counts and the links,
// and the choice is remembered in the browser (also seeded from the cleaning page's streets).
(function () {
  "use strict";
  const root = document.querySelector("[data-up]");
  if (!root) return;
  const form = root.querySelector("[data-up-form]");
  const toks = root.querySelector("[data-up-toks]");
  const add = root.querySelector("#up-add");
  const slugOf = new Map([...document.querySelectorAll("#up-streets option")].map((o) => [o.value, o.dataset.slug]));
  const KEY = "upozorneni";
  const store = {
    get() { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; } },
    set(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* private window */ } },
  };
  root.querySelector("[data-up-apply]").hidden = true;

  const streets = () => [...toks.querySelectorAll("input[name=ulice]")].map((i) => i.value);
  const kinds = () => [...form.querySelectorAll("input[name=co]:checked")].map((i) => i.value);
  const query = () => {
    const p = new URLSearchParams();
    if (streets().length) p.set("ulice", streets().join(","));
    // the default (every kind but the opt-in ones) needs no co=
    const k = kinds(), def = [...form.querySelectorAll("input[name=co]")].filter((i) => !i.dataset.optin).map((i) => i.value);
    if (k.length && (k.length !== def.length || k.some((x) => !def.includes(x)))) p.set("co", k.join(","));
    return p.toString().replace(/%2C/g, ",");
  };

  function token(name, slug) {
    const li = document.createElement("li");
    li.className = "tok";
    const hid = Object.assign(document.createElement("input"), { type: "hidden", name: "ulice", value: slug });
    const x = document.createElement("button");
    x.type = "button";
    x.setAttribute("aria-label", "Odebrat " + name);
    x.innerHTML = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
    li.append(hid, name, x);
    return li;
  }

  function row(r) {
    const li = document.createElement("li"), a = document.createElement("a");
    a.href = r.href;
    const d = Object.assign(document.createElement("span"), { className: "pd-rd", textContent: r.date });
    const t = Object.assign(document.createElement("span"), { className: "pd-rt" });
    t.append(Object.assign(document.createElement("b"), { textContent: r.head }), Object.assign(document.createElement("span"), { textContent: r.sub }));
    const s = Object.assign(document.createElement("span"), { className: r.cls, textContent: r.status });
    a.append(d, t, s);
    li.append(a);
    return li;
  }

  let seq = 0;
  async function refresh() {
    const q = query(), n = ++seq, any = streets().length > 0;
    history.replaceState(null, "", location.pathname + (q ? "?" + q : ""));
    store.set({ ulice: streets(), co: kinds() });
    root.querySelector("[data-up-ways]").hidden = !any;
    root.querySelector("[data-up-none]").hidden = any;
    const rows = root.querySelector("[data-up-rows]"), empty = root.querySelector("[data-up-empty]");
    if (!any) {
      rows.textContent = "";
      root.querySelectorAll("[data-up-count]").forEach((c) => (c.hidden = true));
      empty.textContent = "Až vyberete ulice, ukážeme tu, co by vám přišlo.";
      empty.hidden = false;
      return;
    }
    let out;
    try { out = await (await fetch("/muj-prehled/nahled.json?" + q)).json(); } catch { return; }
    if (n !== seq) return;      // a newer change is on its way
    rows.replaceChildren(...out.rows.map(row));
    empty.textContent = "Za posledních 60 dní se ve vybraných ulicích nic takového nestalo.";
    empty.hidden = out.rows.length > 0;
    root.querySelectorAll("[data-up-count]").forEach((c) => { c.textContent = out.counts[c.dataset.upCount] ?? 0; c.hidden = false; });
    const cal = root.querySelector("[data-up-cal]");
    cal.href = out.webcal; cal.dataset.https = out.https;
    root.querySelector("[data-up-rss]").dataset.copy = out.feed;
    if (pushSub) {
      post("/muj-prehled/odber", { subscription: pushSub.toJSON(), ulice: streets(), co: kinds() })
        .then((r) => saved(r.ok ? "Uloženo. Upozornění vám teď budou chodit podle nového výběru."
                                : "Změnu se nepodařilo uložit. Zkuste to prosím znovu."))
        .catch(() => saved("Změnu se nepodařilo uložit. Zkuste to prosím znovu."));
    } else {
      saved("Výběr je uložený v tomto prohlížeči. Pokud odebíráte informace pomocí RSS nebo kalendáře, aktualizujte si odkaz.");
    }
  }

  // a change of the choice says it took: the notifications' subscription saved, or the links new
  const savedEl = document.querySelector("[data-up-saved]");
  let savedTimer;
  function saved(text) {
    if (!savedEl) return;
    savedEl.textContent = text;
    savedEl.hidden = false;
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => (savedEl.hidden = true), 5000);
  }

  // --- notifications (Web Push): the row shows only where the browser can do it ----------------
  const pushRow = root.querySelector("[data-up-push]");
  let pushSub = null;
  const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const b64 = (s) => Uint8Array.from(atob((s + "===".slice((s.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
  async function setupPush() {
    if (!pushRow) return;
    const btn = pushRow.querySelector("[data-up-push-btn]"), st = pushRow.querySelector("[data-up-push-st]");
    const say = (t) => { st.textContent = t; st.hidden = !t; };
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    const can = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    if (!can) {
      if (!ios) return;            // a browser without notifications: the row stays hidden
      pushRow.hidden = false; btn.hidden = true;
      say("Na iPhonu klepněte na Sdílet a zvolte Přidat na plochu. Pak Pětku otevřete z plochy a upozornění zapněte tam.");
      return;
    }
    pushRow.hidden = false;
    const reg = await navigator.serviceWorker.register("/sw.js");
    pushSub = await reg.pushManager.getSubscription();
    const show = () => {
      btn.textContent = pushSub ? "Vypnout" : "Zapnout";
      btn.classList.toggle("btn-o", !!pushSub);
      if (Notification.permission === "denied") say("Upozornění máte pro Pětku v prohlížeči zakázaná. Povolte je v nastavení stránky (ikona vedle adresy).");
      else say(pushSub ? "Upozornění jsou v tomto prohlížeči zapnutá. Když změníte výběr, upraví se samy." : "");
    };
    show();
    if (pushSub) post("/muj-prehled/odber", { subscription: pushSub.toJSON(), ulice: streets(), co: kinds() });
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        if (pushSub) {
          await post("/muj-prehled/odber/zrusit", { endpoint: pushSub.endpoint, auth: pushSub.toJSON().keys.auth });
          await pushSub.unsubscribe();
          pushSub = null;
        } else if (await Notification.requestPermission() === "granted") {
          // a browser that cannot reach its push service may never answer: give up after 20 s
          const sub = await Promise.race([
            reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(pushRow.dataset.vapid) }),
            new Promise((_, no) => setTimeout(() => no(new Error("timeout")), 20000))]);
          const r = await post("/muj-prehled/odber", { subscription: sub.toJSON(), ulice: streets(), co: kinds() });
          if (!r.ok) { await sub.unsubscribe(); throw new Error(r.status); }
          pushSub = sub;
        }
      } catch {
        say("Upozornění se nepodařilo zapnout. Zkuste to prosím znovu.");
        btn.disabled = false;
        return;
      }
      btn.disabled = false;
      show();
    });
  }

  function pick() {
    const slug = slugOf.get(add.value.trim());
    if (!slug) return;
    if (!streets().includes(slug)) toks.append(token(add.value.trim(), slug));
    add.value = "";
    refresh();
  }
  add.addEventListener("combo-pick", pick);
  add.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); pick(); } });
  toks.addEventListener("click", (e) => {
    const x = e.target.closest(".tok button");
    if (!x) return;
    e.preventDefault();
    const li = x.closest(".tok"), next = li.nextElementSibling || li.previousElementSibling;
    li.remove();
    (next ? next.querySelector("button") : add).focus();
    refresh();
  });
  form.addEventListener("change", (e) => { if (e.target.name === "co") refresh(); });
  form.addEventListener("submit", (e) => e.preventDefault());

  setupPush();

  // A first visit without streets in the URL: the remembered choice, or the cleaning page's streets
  if (!location.search) {
    const saved = store.get();
    let seed = saved && saved.ulice && saved.ulice.length ? saved : null;
    if (!seed) { try { const c = JSON.parse(localStorage.getItem("cisteni-ulice") || "[]"); if (c.length) seed = { ulice: c }; } catch { /* none */ } }
    if (seed) {
      const p = new URLSearchParams({ ulice: seed.ulice.join(",") });
      if (seed.co && seed.co.length) p.set("co", seed.co.join(","));
      location.replace(location.pathname + "?" + p);
    }
  }
})();
