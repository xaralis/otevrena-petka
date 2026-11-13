// Podněty: the tiles open one shared detail panel in place (without JS each tile is a link to
// ?detail=…, which the server renders open), the phone's "Všech N druhů", and „Kde“: the map
// (petkamap.js) with its filters and list.
//   filters  Vše / Čeká / Vyřešeno and Druh, with counts; without JS links and a GET form, here
//            applied in place (history.replaceState); any link to #kde on the page sets them too
//   map      clusters: a white disc sized by the count, a red-hatched wedge for the share that
//            waits, the count inside (canvas images made on demand); a click zooms in. Single
//            reports: a 14 px circle, hatched when it waits.
//   card     pointing at a report (or its row) shows its card (mapTip.card); it stays open while
//            pointed at, a click or a tap pins it, a click elsewhere or Escape closes it
//   list     the reports in view after the filters, newest first, 15 at a time
(function () {
  const LIST = 15;

  // --- tiles ----------------------------------------------------------------------------------
  const tiles = document.querySelectorAll("[data-pd-tile]");
  const details = document.querySelectorAll("[data-pd-detail]");
  tiles.forEach((t) => {
    t.setAttribute("role", "button");
    t.addEventListener("click", (e) => {
      e.preventDefault();
      const key = t.dataset.pdTile, open = t.getAttribute("aria-expanded") !== "true";
      tiles.forEach((x) => x.setAttribute("aria-expanded", String(open && x === t)));
      details.forEach((d) => (d.hidden = !(open && d.dataset.pdDetail === key)));
      // the open tile stays out of the address: it is a view, not something to link to
    });
    t.addEventListener("keydown", (e) => { if (e.key === " ") { e.preventDefault(); t.click(); } });
  });

  // --- every category on a phone --------------------------------------------------------------
  const more = document.querySelector("[data-pd-more]");
  if (more) more.addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelectorAll(".pd-more").forEach((li) => li.classList.remove("pd-more"));
    more.parentElement.remove();
  });

  // --- „Kde“ ---------------------------------------------------------------------------------
  const el = document.querySelector("[data-pd-map]");
  const form = document.querySelector("[data-pd-filter]");
  if (!el || !form || !window.maplibregl || !window.pmtiles || !window.mapTip || !window.petkaMap) return;
  const data = JSON.parse(document.getElementById("pd-points").textContent);
  const feats = data.features;                      // newest first
  const byId = new Map(feats.map((f) => [f.properties.id, f]));
  const wrap = el.parentElement;
  const list = document.querySelector("[data-pd-rows]");
  const head = document.getElementById("pd-side-h");
  const seg = form.querySelectorAll("[data-stav]");
  const select = form.querySelector("select[name=druh]");
  const go = form.querySelector(".pd-go");
  const DETAIL = window.petkaMap ? window.petkaMap.DETAIL : "";
  if (go) go.hidden = true;

  // the filter, from the address the server rendered
  const params = new URLSearchParams(location.search);
  const known = (k) => feats.some((f) => f.properties.k === k);
  // the state as the address writes it: "" = waiting (the default), "vyreseno", "vse" = every state
  let stav = ["vyreseno", "vse"].includes(params.get("stav")) ? params.get("stav") : "";
  let druh = /^\d+$/.test(params.get("druh") || params.get("kategorie") || "") ? +(params.get("druh") || params.get("kategorie")) : null;
  if (druh !== null && !known(druh)) druh = null;
  // ?ulice=<slug>: one street, its name in the chip the server rendered ("Všechny ulice" clears it)
  const fold = (t) => (t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
  const chip = form.querySelector("[data-pd-street]");
  let street = chip ? fold(chip.dataset.pdStreet) : null;
  const slug = params.get("ulice");
  const match = (p, st, dr) => (st === "vse" || p.o === (st || "ceka")) && (dr === null || p.k === dr)
    && (street === null || fold(p.s) === street);
  const current = () => feats.filter((f) => match(f.properties, stav, druh));
  Array.from(select.options).forEach((o) => (o.dataset.name = o.textContent.replace(/ \(\d+\)$/, "")));

  function counts() {
    seg.forEach((a) => {
      const k = a.dataset.stav;
      a.querySelector("b").textContent = feats.filter((f) => match(f.properties, k, druh)).length;
      if (k === stav) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
    });
    Array.from(select.options).forEach((o) => {
      const n = feats.filter((f) => match(f.properties, stav, o.value ? +o.value : null)).length;
      o.textContent = `${o.dataset.name} (${n})`;
    });
    select.value = druh === null ? "" : String(druh);
  }

  function remember() {
    const url = new URL(location.href);
    stav ? url.searchParams.set("stav", stav) : url.searchParams.delete("stav");
    druh !== null ? url.searchParams.set("druh", druh) : url.searchParams.delete("druh");
    street !== null ? url.searchParams.set("ulice", slug) : url.searchParams.delete("ulice");
    ["kategorie", "pocet"].forEach((k) => url.searchParams.delete(k));
    url.hash = "";
    history.replaceState(null, "", url);
    // the period switch and the tiles keep the filter
    document.querySelectorAll(".pd-switch a, [data-pd-tile]").forEach((a) => {
      const u = new URL(a.href);
      stav ? u.searchParams.set("stav", stav) : u.searchParams.delete("stav");
      druh !== null ? u.searchParams.set("druh", druh) : u.searchParams.delete("druh");
      street !== null ? u.searchParams.set("ulice", slug) : u.searchParams.delete("ulice");
      a.href = u.pathname + u.search + u.hash;
    });
    let h = form.querySelector("input[name=stav]");
    if (stav && !h) { h = document.createElement("input"); h.type = "hidden"; h.name = "stav"; form.prepend(h); }
    if (h) { if (stav) h.value = stav; else h.remove(); }
  }

  let apply = () => {}, fitAll = () => {};      // the map's part, once it is there
  function filter(st, dr) {
    stav = st;
    druh = dr !== null && known(dr) ? dr : null;
    counts();
    remember();
    apply();
  }
  counts();
  seg.forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); filter(a.dataset.stav, druh); }));
  if (chip) chip.querySelector("[data-pd-street-clear]").addEventListener("click", (e) => {
    e.preventDefault();
    street = null;
    chip.remove();
    const h = form.querySelector("input[name=ulice]");
    if (h) h.remove();
    filter(stav, druh);
    fitAll();          // the whole obvod again
  });
  select.addEventListener("change", () => filter(stav, select.value ? +select.value : null));
  form.addEventListener("submit", (e) => { e.preventDefault(); filter(stav, select.value ? +select.value : null); });
  // the table, the waiting categories, the highlight: links to #kde set the filter and scroll
  document.querySelectorAll('main a[href*="#kde"]').forEach((a) => {
    if (a.closest("[data-pd-filter], .pd-side")) return;
    a.addEventListener("click", (e) => {
      const u = new URL(a.href);
      if (u.pathname !== location.pathname || (u.searchParams.get("obdobi") || "") !== (params.get("obdobi") || "")) return;
      e.preventDefault();
      const d = u.searchParams.get("druh");
      filter(u.searchParams.get("stav") || "", d ? +d : null);
      document.getElementById("kde").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    });
  });

  // --- the map itself (petkamap.js) ---
  const P = window.petkaMap, plural = P.plural, dm = P.dm;
  const bounds = (fs) => P.bounds(fs);
  const start = bounds(current().length ? current() : feats);
  P.create(el, { bounds: start || undefined, fitBoundsOptions: { padding: 30, maxZoom: 16 }, maxBounds: null, maxZoom: 18, font: true })
    .then(draw);

  function draw(map) {
    const shown = () => ({ type: "FeatureCollection", features: current() });
    let close = () => {};
    const rep = P.reports(map, { id: "pd", data: shown(), wrap, closeOutside: () => close() });
    const card = rep.card;

    // a state is a report's id; pointing shows its card and outlines it, a click pins it
    const link = P.linker((id) => {
      list.querySelectorAll("li.on").forEach((li) => li.classList.remove("on"));
      if (id === null) { card.hide(); rep.ring([]); return; }
      card.show(id, { enter: () => link.keep(), leave: () => link.leave() });
      rep.ring([byId.get(id)]);
      const row = list.querySelector(`li[data-id="${id}"]`);
      if (row) row.classList.add("on");
    }, { delay: 250, stick: true, within: () => [wrap, list] });
    close = link.close;

    map.on("mouseenter", rep.cl, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", rep.cl, () => (map.getCanvas().style.cursor = ""));
    map.on("mousemove", rep.pt, (e) => { map.getCanvas().style.cursor = "pointer"; link.hover(e.features[0].properties.id); });
    map.on("mouseleave", rep.pt, () => { map.getCanvas().style.cursor = ""; link.leave(); });
    map.on("click", (e) => {
      const f = map.queryRenderedFeatures(e.point, { layers: [rep.pt, rep.cl] })[0];
      if (!f) { link.close(); return; }
      if (f.layer.id === rep.cl) { link.close(); rep.zoomInto(f); return; }
      // a report: the card has a toggle and a link, so a click (a tap on phones) pins it
      link.pin(f.properties.id);
    });

    // --- the list: what the map shows ---
    let limit = LIST;
    const moreLink = document.querySelector("[data-pd-rows-more]") || (() => {
      const a = document.createElement("a");
      a.className = "pd-rows-more"; a.href = "#kde"; a.dataset.pdRowsMore = "";
      list.after(a);
      return a;
    })();
    moreLink.textContent = "Další podněty";
    moreLink.setAttribute("role", "button");
    moreLink.addEventListener("click", (e) => { e.preventDefault(); limit += LIST; render(); });
    function row(f) {
      const p = f.properties;
      const li = document.createElement("li"), a = document.createElement("a");
      li.dataset.id = p.id;
      a.href = DETAIL + p.id;
      a.target = "_blank"; a.rel = "noopener";     // the report opens on Dej Tip beside this page
      const d = document.createElement("span"), t = document.createElement("span"), b = document.createElement("b"),
            s = document.createElement("span");
      d.className = "pd-rd"; d.textContent = dm(p.t).replace(/ \d{4}$/, "");
      t.className = "pd-rt"; b.textContent = p.c; t.appendChild(b);
      if (p.s) { const st = document.createElement("span"); st.textContent = p.s; t.appendChild(st); }
      s.className = p.o === "ceka" ? "st st-no" : "st"; s.textContent = p.w;
      a.append(d, t, s);
      li.appendChild(a);
      link.wire(a, () => p.id);
      return li;
    }
    function render(reset) {
      if (reset) limit = LIST;
      const b = map.getBounds();
      const inView = current().filter((f) => b.contains(f.geometry.coordinates));
      head.textContent = `V mapě ${inView.length} ${plural(inView.length, "podnět", "podněty", "podnětů")}, nejnovější`;
      list.replaceChildren(...inView.slice(0, limit).map(row));
      moreLink.hidden = inView.length <= limit;
      if (card.id !== null) { const r = list.querySelector(`li[data-id="${card.id}"]`); if (r) r.classList.add("on"); }
    }
    map.on("moveend", () => render(true));
    render(true);

    fitAll = () => P.fit(map, current(), { padding: 30, maxZoom: 16 });
    apply = () => {
      link.close();
      rep.setData(shown());
      // nothing of the new choice in view: show all of it
      const b = map.getBounds(), fs = current();
      if (fs.length && !fs.some((f) => b.contains(f.geometry.coordinates))) P.fit(map, fs, { padding: 30, maxZoom: 16 });
      else render(true);
    };
  }
})();
