// Podněty: the tiles open one shared detail panel in place (without JS each tile is a link to
// ?detail=…, which the server renders open), the phone's "Všech N druhů", and „Kde“: the map
// (self-hosted MapLibre + PMTiles, like cisteni.js) with its filters and list.
//   filters  Vše / Čeká / Vyřešeno and Druh, with counts; without JS links and a GET form, here
//            applied in place (history.replaceState); any link to #kde on the page sets them too
//   map      clusters: a white disc sized by the count, a red-hatched wedge for the share that
//            waits, the count inside (canvas images made on demand); a click zooms in. Single
//            reports: a 14 px circle, hatched when it waits.
//   card     pointing at a report (or its row) shows its card (mapTip.card); it stays open while
//            pointed at, a click or a tap pins it, a click elsewhere or Escape closes it
//   list     the reports in view after the filters, newest first, 15 at a time
(function () {
  const INK = "#191c1f", RED = "#de091c", PINK = "#f4a3aa";
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
      const url = new URL(location.href);
      if (open) url.searchParams.set("detail", key); else url.searchParams.set("detail", "zadny");
      url.hash = "";
      history.replaceState(null, "", url);
      // the period switch keeps what is open
      document.querySelectorAll(".pd-switch a").forEach((a) => {
        const u = new URL(a.href);
        if (open && key === "ceka") u.searchParams.delete("detail"); else u.searchParams.set("detail", open ? key : "zadny");
        a.href = u.pathname + u.search;
      });
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
  if (!el || !form || !window.maplibregl || !window.pmtiles || !window.mapTip) return;
  const data = JSON.parse(document.getElementById("pd-points").textContent);
  const feats = data.features;                      // newest first
  const byId = new Map(feats.map((f) => [f.properties.id, f]));
  const wrap = el.parentElement;
  const list = document.querySelector("[data-pd-rows]");
  const head = document.getElementById("pd-side-h");
  const seg = form.querySelectorAll("[data-stav]");
  const select = form.querySelector("select[name=druh]");
  const go = form.querySelector(".pd-go");
  const DETAIL = "https://amg.dejtip.eu/pardubice/?id=";
  if (go) go.hidden = true;

  // the filter, from the address the server rendered
  const params = new URLSearchParams(location.search);
  const known = (k) => feats.some((f) => f.properties.k === k);
  // the state as the address writes it: "" = waiting (the default), "vyreseno", "vse" = every state
  let stav = ["vyreseno", "vse"].includes(params.get("stav")) ? params.get("stav") : "";
  let druh = /^\d+$/.test(params.get("druh") || params.get("kategorie") || "") ? +(params.get("druh") || params.get("kategorie")) : null;
  if (druh !== null && !known(druh)) druh = null;
  const match = (p, st, dr) => (st === "vse" || p.o === (st || "ceka")) && (dr === null || p.k === dr);
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
    ["kategorie", "pocet"].forEach((k) => url.searchParams.delete(k));
    url.hash = "";
    history.replaceState(null, "", url);
    // the period switch and the tiles keep the filter
    document.querySelectorAll(".pd-switch a, [data-pd-tile]").forEach((a) => {
      const u = new URL(a.href);
      stav ? u.searchParams.set("stav", stav) : u.searchParams.delete("stav");
      druh !== null ? u.searchParams.set("druh", druh) : u.searchParams.delete("druh");
      a.href = u.pathname + u.search + u.hash;
    });
    let h = form.querySelector("input[name=stav]");
    if (stav && !h) { h = document.createElement("input"); h.type = "hidden"; h.name = "stav"; form.prepend(h); }
    if (h) { if (stav) h.value = stav; else h.remove(); }
  }

  let apply = () => {};          // the map's part, once it is there
  function filter(st, dr) {
    stav = st;
    druh = dr !== null && known(dr) ? dr : null;
    counts();
    remember();
    apply();
  }
  counts();
  seg.forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); filter(a.dataset.stav, druh); }));
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

  // --- the map itself ---
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  const abs = (u) => location.origin + u;
  const font = document.fonts && document.fonts.load ? document.fonts.load('800 12px "Bricolage Grotesque"').catch(() => {}) : Promise.resolve();
  Promise.all([fetch(el.dataset.style).then((r) => r.json()), font]).then(([s]) => {
    s.sprite = abs(s.sprite);
    s.glyphs = abs(s.glyphs);
    s.sources.protomaps.url = "pmtiles://" + abs(el.dataset.tiles);
    const b = bounds(current().length ? current() : feats);
    const map = new maplibregl.Map({
      container: el, style: s, bounds: b || undefined, fitBoundsOptions: { padding: 30, maxZoom: 16 },
      minZoom: 11, maxZoom: 18, attributionControl: { compact: true }, cooperativeGestures: true,
      locale: {
        "CooperativeGesturesHandler.WindowsHelpText": "Mapu přiblížíte s klávesou Ctrl a kolečkem myši",
        "CooperativeGesturesHandler.MacHelpText": "Mapu přiblížíte s klávesou ⌘ a kolečkem myši",
        "CooperativeGesturesHandler.MobileHelpText": "Mapou posunete dvěma prsty",
        "NavigationControl.ZoomIn": "Přiblížit", "NavigationControl.ZoomOut": "Oddálit",
      },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => draw(map));
  });

  function bounds(fs) {
    if (!fs.length) return null;
    const b = new maplibregl.LngLatBounds();
    fs.forEach((f) => b.extend(f.geometry.coordinates));
    return b;
  }

  // the hatch of .pending-alert, at pixelRatio 2: pink with red stripes 3 px wide every 6 px
  function hatch(g, size) {
    g.fillStyle = PINK; g.fillRect(0, 0, size, size);
    g.strokeStyle = RED; g.lineWidth = 6;
    for (let x = -size; x < 2 * size; x += 12) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x + size, size); g.stroke(); }
  }
  function canvas(css) {
    const c = document.createElement("canvas");
    c.width = c.height = css * 2;
    return [c, c.getContext("2d")];
  }
  // one report: a 14 px circle with a 2 px ink border, white or hatched
  function point(waiting) {
    const [c, g] = canvas(18), m = 18;
    g.save(); g.beginPath(); g.arc(m, m, 14, 0, 2 * Math.PI); g.clip();
    if (waiting) hatch(g, 36); else { g.fillStyle = "#fff"; g.fill(); }
    g.restore();
    g.beginPath(); g.arc(m, m, 13, 0, 2 * Math.PI); g.lineWidth = 4; g.strokeStyle = INK; g.stroke();
    return g.getImageData(0, 0, 36, 36);
  }
  // a cluster of n, w of them waiting: radius 10 + 1.7 √n px, the hatched wedge from twelve
  // o'clock, an ink ring, a white middle with the count
  function cluster(n, w) {
    const r = 10 + 1.7 * Math.sqrt(n), css = Math.ceil(2 * r + 4), [c, g] = canvas(css), m = css, R = 2 * r;
    g.beginPath(); g.arc(m, m, R, 0, 2 * Math.PI); g.fillStyle = "#fff"; g.fill();
    if (w > 0) {
      g.save(); g.beginPath(); g.moveTo(m, m);
      g.arc(m, m, R, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * Math.min(1, w / n)); g.closePath(); g.clip();
      hatch(g, 2 * css); g.restore();
    }
    g.beginPath(); g.arc(m, m, R - 2, 0, 2 * Math.PI); g.lineWidth = 4; g.strokeStyle = INK; g.stroke();
    g.beginPath(); g.arc(m, m, R - 10, 0, 2 * Math.PI); g.fillStyle = "#fff"; g.fill();
    g.fillStyle = INK; g.font = '800 23px "Bricolage Grotesque", system-ui, sans-serif';
    g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(String(n), m, m + 1);
    return g.getImageData(0, 0, 2 * css, 2 * css);
  }

  // --- words of the card and the list ---
  const plural = (n, one, few, many) => (n === 1 ? one : n >= 2 && n <= 4 ? few : many);
  const thisYear = new Date().getFullYear();
  function dm(iso) { const [y, mo, d] = iso.slice(0, 10).split("-").map(Number); return `${d}. ${mo}.` + (y !== thisYear ? ` ${y}` : ""); }
  function when(iso) {
    const h = +iso.slice(11, 13), mi = iso.slice(14, 16);
    return `${dm(iso)} ${[2, 3, 4, 12, 13, 14, 20, 21, 22, 23].includes(h) ? "ve" : "v"} ${h}:${mi}`;
  }
  function state(p) {
    if (p.o !== "ceka") return [p.w, ""];
    const n = p.wd || 0;
    return [n < 1 ? "čeká od dneška" : `čeká ${n} ${plural(n, "den", "dny", "dní")}`, "st-no"];
  }

  function draw(map) {
    const empty = { type: "FeatureCollection", features: [] };
    map.addImage("pd-pt", point(false), { pixelRatio: 2 });
    map.addImage("pd-pt-w", point(true), { pixelRatio: 2 });
    map.on("styleimagemissing", (e) => {
      const m = /^pd-c-(\d+)-(\d+)$/.exec(e.id);
      if (m && !map.hasImage(e.id)) map.addImage(e.id, cluster(+m[1], +m[2]), { pixelRatio: 2 });
    });
    const shown = () => ({ type: "FeatureCollection", features: current() });
    map.addSource("pd", { type: "geojson", data: shown(), cluster: true, clusterRadius: 44, clusterMaxZoom: 16,
                          clusterProperties: { waiting: ["+", ["case", ["==", ["get", "o"], "ceka"], 1, 0]] } });
    map.addSource("pd-hl", { type: "geojson", data: empty });
    const solo = { "icon-allow-overlap": true, "icon-ignore-placement": true };
    map.addLayer({ id: "pd-pt", type: "symbol", source: "pd", filter: ["!", ["has", "point_count"]],
                   layout: { ...solo, "icon-image": ["case", ["==", ["get", "o"], "ceka"], "pd-pt-w", "pd-pt"],
                             "symbol-sort-key": ["case", ["==", ["get", "o"], "ceka"], 1, 0] } });
    map.addLayer({ id: "pd-cl", type: "symbol", source: "pd", filter: ["has", "point_count"],
                   layout: { ...solo, "icon-image": ["concat", "pd-c-", ["to-string", ["get", "point_count"]], "-",
                                                     ["to-string", ["get", "waiting"]]],
                             "symbol-sort-key": ["get", "point_count"] } });
    map.addLayer({ id: "pd-ring", type: "circle", source: "pd-hl",
                   paint: { "circle-radius": 11, "circle-opacity": 0, "circle-stroke-color": INK, "circle-stroke-width": 3 } });

    // --- the card ---
    let open = null, pinned = false, card = null, timer = null;
    const place = () => {
      if (!card || open === null) return;
      if (card.fit) card.fit();
      const p = map.project(byId.get(open).geometry.coordinates);
      if (p.x < -10 || p.y < -10 || p.x > el.clientWidth + 10 || p.y > el.clientHeight + 10) { close(); return; }
      window.mapTip.place(card, p.x, p.y, el.clientWidth, el.clientHeight);
    };
    function show(id) {
      clearTimeout(timer);
      if (open !== id) {
        const f = byId.get(id), p = f.properties;
        const [word, cls] = state(p);
        const facts = [["nahlášeno", when(p.t)]];
        if (p.a) facts.push(["odpověď úřadu", when(p.a)]);
        facts.push(["stav", word, cls]);
        if (card) card.remove();
        card = window.mapTip.card({
          photo: p.p, alt: `Fotka z podnětu: ${p.c}${p.s ? ", " + p.s : ""}`, title: p.c, place: p.s, text: p.d,
          facts, href: DETAIL + p.id, link: "Otevřít na Dej Tipu",
        }, place);
        card.addEventListener("mouseenter", () => clearTimeout(timer));
        card.addEventListener("mouseleave", () => { if (!pinned) later(); });
        wrap.appendChild(card);
        open = id;
        map.getSource("pd-hl").setData({ type: "FeatureCollection", features: [f] });
      }
      place();
      card.classList.add("on");
      list.querySelectorAll("li.on").forEach((li) => li.classList.remove("on"));
      const row = list.querySelector(`li[data-id="${id}"]`);
      if (row) row.classList.add("on");
    }
    function close() {
      clearTimeout(timer);
      pinned = false;
      open = null;
      if (card) { card.remove(); card = null; }
      map.getSource("pd-hl").setData(empty);
      list.querySelectorAll("li.on").forEach((li) => li.classList.remove("on"));
    }
    const later = () => { clearTimeout(timer); timer = setTimeout(close, 250); };

    map.on("mouseenter", "pd-cl", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "pd-cl", () => (map.getCanvas().style.cursor = ""));
    map.on("mousemove", "pd-pt", (e) => {
      map.getCanvas().style.cursor = "pointer";
      if (!pinned) show(e.features[0].properties.id);
    });
    map.on("mouseleave", "pd-pt", () => { map.getCanvas().style.cursor = ""; if (!pinned) later(); });
    map.on("click", (e) => {
      const f = map.queryRenderedFeatures(e.point, { layers: ["pd-pt", "pd-cl"] })[0];
      if (!f) { close(); return; }
      if (f.layer.id === "pd-cl") {
        close();
        map.getSource("pd").getClusterExpansionZoom(f.properties.cluster_id)
          .then((z) => map.easeTo({ center: f.geometry.coordinates, zoom: Math.min(z, map.getMaxZoom()) }));
        return;
      }
      // a report: the card has a toggle and a link, so a click (a tap on phones) pins it
      show(f.properties.id);
      pinned = true;
    });
    map.on("move", place);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && open !== null) close(); });
    document.addEventListener("click", (e) => {
      if (pinned && !wrap.contains(e.target) && !list.contains(e.target)) close();
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
      d.className = "pd-rd"; d.textContent = dm(p.t).replace(/ \d{4}$/, "");
      t.className = "pd-rt"; b.textContent = p.c; t.appendChild(b);
      if (p.s) { const st = document.createElement("span"); st.textContent = p.s; t.appendChild(st); }
      s.className = p.o === "ceka" ? "st st-no" : "st"; s.textContent = p.w;
      a.append(d, t, s);
      li.appendChild(a);
      a.addEventListener("mouseenter", () => { if (!pinned) show(p.id); });
      a.addEventListener("focus", () => { if (!pinned) show(p.id); });
      a.addEventListener("mouseleave", () => { if (!pinned) later(); });
      a.addEventListener("blur", () => { if (!pinned) later(); });
      return li;
    }
    function render(reset) {
      if (reset) limit = LIST;
      const b = map.getBounds();
      const inView = current().filter((f) => b.contains(f.geometry.coordinates));
      head.textContent = `V mapě ${inView.length} ${plural(inView.length, "podnět", "podněty", "podnětů")}, nejnovější`;
      list.replaceChildren(...inView.slice(0, limit).map(row));
      moreLink.hidden = inView.length <= limit;
      if (open !== null) { const r = list.querySelector(`li[data-id="${open}"]`); if (r) r.classList.add("on"); }
    }
    map.on("moveend", () => render(true));
    render(true);

    apply = () => {
      close();
      map.getSource("pd").setData(shown());
      // nothing of the new choice in view: show all of it
      const b = map.getBounds(), fs = current();
      if (fs.length && !fs.some((f) => b.contains(f.geometry.coordinates))) {
        map.fitBounds(bounds(fs), { padding: 30, maxZoom: 16 });
      } else render(true);
    };
  }
})();
