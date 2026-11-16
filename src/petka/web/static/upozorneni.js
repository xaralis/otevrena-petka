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
    const k = kinds(), all = form.querySelectorAll("input[name=co]").length;
    if (k.length && k.length < all) p.set("co", k.join(","));
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
    try { out = await (await fetch("/zapojte-se/upozorneni/nahled.json?" + q)).json(); } catch { return; }
    if (n !== seq) return;      // a newer change is on its way
    rows.replaceChildren(...out.rows.map(row));
    empty.textContent = "Za posledních 30 dní se ve vybraných ulicích nic takového nestalo.";
    empty.hidden = out.rows.length > 0;
    root.querySelectorAll("[data-up-count]").forEach((c) => { c.textContent = out.counts[c.dataset.upCount] ?? 0; c.hidden = false; });
    const cal = root.querySelector("[data-up-cal]");
    cal.href = out.webcal; cal.dataset.https = out.https;
    root.querySelector("[data-up-rss]").dataset.copy = out.feed;
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
