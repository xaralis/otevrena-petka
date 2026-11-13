// A street's „Aktuálně“ (self-hosted MapLibre + PMTiles, like aktualne.js and podnety.js) and the
// short placeholder of the street search on phones.
//   street    the base map's road of that name (OpenStreetMap), RÚIAN's line where it has none
//   cleaning  this year's cleaned places on the street: the upcoming ones grey, the one pointed
//             at (or its row) ink with its tooltip; past ones drawn only while their row is
//   reports   points and clusters as on /verejny-prostor/podnety (reports.js), the card on a
//             report; a click pins it (on phones under the map), Escape or a click elsewhere
//             closes it, a click on a cluster zooms in
//   marks     úřední deska notices naming the street: hatched = traffic, white = the kind's icon
// The list's rows and the map point at each other: a row lights its features up (a report's
// point or the cluster it is in outlined, a single report's card), a feature its row.
// Data: <script id=ul-map-json> from ulice/web.py street().
(function () {
  const INK = "#191c1f", GREY = "#7d838b";
  const STEP = 18;        // rows „Další“ adds, q.ROWS

  if (window.matchMedia("(max-width: 600px)").matches)
    document.querySelectorAll("input[data-short]").forEach((i) => (i.placeholder = i.dataset.short));

  const list = document.querySelector("[data-ul-rows]");
  const more = document.querySelector("[data-ul-more]");
  if (list && more) {
    more.setAttribute("role", "button");
    more.addEventListener("click", (e) => {
      e.preventDefault();
      const hidden = list.querySelectorAll("li[hidden]");
      Array.from(hidden).slice(0, STEP).forEach((li) => (li.hidden = false));
      if (hidden.length <= STEP) more.remove();
    });
  }

  const el = document.querySelector("[data-ul-map]");
  if (!el || !window.maplibregl || !window.pmtiles || !window.mapTip || !window.reportMap) return;
  const R = window.reportMap;
  const data = JSON.parse(document.getElementById(el.dataset.inline).textContent);
  const stage = el.closest(".ul-akt");
  const wrap = el.parentElement;
  const sheet = stage.querySelector("[data-ul-sheet]");
  const narrow = () => window.matchMedia("(max-width: 900px)").matches;
  const reports = data.reports.features;
  const byId = new Map(reports.map((f) => [f.properties.id, f]));
  const idsOf = {};
  reports.forEach((f) => { if (f.properties.row) (idsOf[f.properties.row] ||= []).push(f.properties.id); });
  const rowEl = (k) => (list ? list.querySelector(`li[data-row="${k}"]`) : null);

  // the street in view from the start (RÚIAN's line), the base map's road once it is loaded
  const walk = (b, c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach((x) => walk(b, x)));
  const start = new maplibregl.LngLatBounds();
  walk(start, data.street.coordinates);

  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  const abs = (u) => location.origin + u;
  const font = document.fonts && document.fonts.load ? document.fonts.load('800 12px "Bricolage Grotesque"').catch(() => {}) : Promise.resolve();
  Promise.all([fetch(el.dataset.style).then((r) => r.json()), font]).then(([s]) => {
    s.sprite = abs(s.sprite);
    s.glyphs = abs(s.glyphs);
    s.sources.protomaps.url = "pmtiles://" + abs(el.dataset.tiles);
    const map = new maplibregl.Map({
      container: el, style: s, bounds: start.isEmpty() ? [[15.738, 49.996], [15.812, 50.043]] : start,
      fitBoundsOptions: { padding: 40, maxZoom: 17 }, maxBounds: [[15.64, 49.95], [15.90, 50.09]],
      minZoom: 11, maxZoom: 18.5, attributionControl: { compact: true }, cooperativeGestures: true,
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

  function draw(map) {
    const empty = { type: "FeatureCollection", features: [] };
    // --- the street and its cleanings ---
    map.addSource("ul-street", { type: "geojson", data: { type: "Feature", geometry: data.street, properties: {} } });
    map.addLayer({ id: "ul-street", type: "line", source: "ul-street", layout: { "line-cap": "round", "line-join": "round" },
                   paint: { "line-color": INK, "line-opacity": 0.14, "line-width": ["interpolate", ["linear"], ["zoom"], 13, 8, 18, 22] } });
    map.addSource("ul-cl", { type: "geojson", data: data.cleaning });
    const w = (extra) => ["interpolate", ["linear"], ["zoom"], 12, 4 + extra, 15, 6 + extra, 18, 9 + extra];
    const line = ["!", ["get", "area"]], area = ["get", "area"], ahead = ["==", ["get", "past"], false];
    const lit = (keys) => ["in", ["get", "row"], ["literal", keys]];
    const round = { "line-cap": "round", "line-join": "round" };
    map.addLayer({ id: "ul-ar-on", type: "fill", source: "ul-cl", filter: ["all", area, lit([])], paint: { "fill-color": INK, "fill-opacity": 0.25 } });
    map.addLayer({ id: "ul-ar", type: "line", source: "ul-cl", filter: ["all", area, ahead],
                   paint: { "line-color": GREY, "line-width": 1.5, "line-dasharray": [2, 2] } });
    map.addLayer({ id: "ul-ar-on-l", type: "line", source: "ul-cl", filter: ["all", area, lit([])], paint: { "line-color": INK, "line-width": 2.5 } });
    map.addLayer({ id: "ul-cl-case", type: "line", source: "ul-cl", filter: ["all", line, ahead], layout: round,
                   paint: { "line-color": "#ffffff", "line-width": w(4) } });
    map.addLayer({ id: "ul-cl", type: "line", source: "ul-cl", filter: ["all", line, ahead], layout: round,
                   paint: { "line-color": GREY, "line-width": w(0) } });
    map.addLayer({ id: "ul-cl-on-case", type: "line", source: "ul-cl", filter: ["all", line, lit([])], layout: round,
                   paint: { "line-color": "#ffffff", "line-width": w(4) } });
    map.addLayer({ id: "ul-cl-on", type: "line", source: "ul-cl", filter: ["all", line, lit([])], layout: round,
                   paint: { "line-color": INK, "line-width": w(0) } });
    map.addLayer({ id: "ul-cl-hit", type: "line", source: "ul-cl", filter: ahead, layout: round,
                   paint: { "line-color": INK, "line-opacity": 0, "line-width": 22 } });
    const labels = map.getStyle().layers.find((l) => l.type === "symbol" && !l.id.startsWith("ul-"));
    if (labels) ["ul-street", "ul-ar-on", "ul-ar", "ul-ar-on-l", "ul-cl-case", "ul-cl", "ul-cl-on-case", "ul-cl-on"]
      .forEach((id) => map.moveLayer(id, labels.id));

    // --- reports ---
    R.images(map, "ur");
    map.addSource("ur", { type: "geojson", data: data.reports, ...R.clustered });
    map.addSource("ur-hl", { type: "geojson", data: empty });
    map.addLayer({ id: "ur-ring", type: "circle", source: "ur-hl",
                   paint: { "circle-radius": ["get", "r"], "circle-opacity": 0, "circle-stroke-color": INK, "circle-stroke-width": 3 } });
    R.layers(map, "ur", "ur");

    // --- tooltips of the cleanings, markers of the notices ---
    const anchor = {}, mark = {};
    data.anchors.forEach((a) => {
      const e = document.createElement("span");
      e.className = "ak-cla";
      e.setAttribute("aria-hidden", "true");
      e.appendChild(window.mapTip.make(a.title, a.text, a.when));
      anchor[a.row] = e;
      new maplibregl.Marker({ element: e }).setLngLat([a.lng, a.lat]).addTo(map);
    });
    data.marks.forEach((m) => {
      const e = document.createElement(m.nid ? "a" : "span");
      if (m.nid) e.href = "/radnice/uredni-deska/" + encodeURIComponent(m.nid);
      e.className = "ak-mk" + (m.traffic ? " ak-mk-t" : "");
      e.tabIndex = 0;
      e.setAttribute("aria-label", m.label);
      const box = document.createElement("i");
      if (!m.traffic) {
        const NS = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(NS, "svg"), use = document.createElementNS(NS, "use");
        svg.setAttribute("width", "19"); svg.setAttribute("height", "19"); svg.setAttribute("aria-hidden", "true");
        use.setAttribute("href", el.dataset.icons + "#" + m.kind);
        svg.appendChild(use);
        box.appendChild(svg);
      }
      e.append(box, window.mapTip.make(m.what, "Úřední deska", m.when));
      mark[m.row] = e;
      new maplibregl.Marker({ element: e }).setLngLat([m.lng, m.lat]).addTo(map);
    });

    // --- which point or cluster shows each report now (recounted when the map settles) ---
    let owner = new Map(), leaves = new Map(), settled = false;
    function recount() {
      const next = new Map(), lv = new Map(), waits = [];
      map.queryRenderedFeatures({ layers: ["ur-pt"] }).forEach((f) =>
        next.set(f.properties.id, { at: f.geometry.coordinates, r: 12, key: "p" + f.properties.id }));
      map.queryRenderedFeatures({ layers: ["ur-cl"] }).forEach((f) => {
        const cid = f.properties.cluster_id;
        if (lv.has(cid)) return;
        lv.set(cid, []);
        waits.push(map.getSource("ur").getClusterLeaves(cid, Infinity, 0).then((fs) => {
          const o = { at: f.geometry.coordinates, r: R.radius(f.properties.point_count) + 3, key: "c" + cid };
          fs.forEach((x) => { next.set(x.properties.id, o); lv.get(cid).push(x.properties.id); });
        }).catch(() => {}));
      });
      Promise.all(waits).then(() => { owner = next; leaves = lv; apply(); });
    }
    map.on("idle", () => { if (!settled) { settled = true; recount(); } });
    map.on("movestart", () => (settled = false));

    // --- one state of the page: the rows lit, the reports outlined, the card ---
    // st = {keys: [row keys], ids: [report ids], card: report id | null}
    const fromRow = (k) => { const ids = idsOf[k] || []; return { keys: [k], ids, card: ids.length === 1 ? ids[0] : null }; };
    const fromReport = (id) => ({ keys: [byId.get(id).properties.row].filter(Boolean), ids: [id], card: id });
    let hovered = null, pinned = null, timer = null, card = null, cardId = null;

    function apply() {
      const st = hovered || pinned;
      stage.querySelectorAll(".on").forEach((e) => { if (e !== card) e.classList.remove("on", "ak-l"); });
      const keys = st ? st.keys : [];
      ["ul-ar-on", "ul-ar-on-l"].forEach((id) => map.setFilter(id, ["all", area, lit(keys)]));
      ["ul-cl-on-case", "ul-cl-on"].forEach((id) => map.setFilter(id, ["all", line, lit(keys)]));
      const edge = el.getBoundingClientRect().right;
      keys.forEach((k) => {
        const r = rowEl(k);
        if (r) r.classList.add("on");
        [anchor[k], mark[k]].forEach((e) => { if (e) { e.classList.add("on"); window.mapTip.side(e, edge); } });
      });
      const rings = new Map();
      (st ? st.ids : []).forEach((id) => { const o = owner.get(id); if (o) rings.set(o.key, o); });
      map.getSource("ur-hl").setData({ type: "FeatureCollection", features: Array.from(rings.values()).map((o) =>
        ({ type: "Feature", geometry: { type: "Point", coordinates: o.at }, properties: { r: o.r } })) });
      showCard(st && st.card != null ? st.card : null);
    }

    function showCard(id) {
      if (id === cardId) { place(); return; }
      if (card) card.remove();
      card = null; cardId = id;
      if (id === null) return;
      card = R.card(byId.get(id).properties, place);
      card.addEventListener("mouseenter", () => clearTimeout(timer));
      card.addEventListener("mouseleave", () => later());
      if (narrow()) sheet.replaceChildren(card); else wrap.appendChild(card);
      place();
      card.classList.add("on");
    }
    function place() {
      if (!card) return;
      if (card.fit) card.fit();
      if (narrow()) return;
      const o = owner.get(cardId), at = o ? o.at : byId.get(cardId).geometry.coordinates;
      const p = map.project(at);
      window.mapTip.place(card, p.x, p.y, el.clientWidth, el.clientHeight);
    }
    const hover = (st) => { clearTimeout(timer); hovered = st; apply(); };
    const later = () => { clearTimeout(timer); timer = setTimeout(() => { hovered = null; apply(); }, 250); };
    const close = () => { clearTimeout(timer); hovered = pinned = null; apply(); };

    map.on("mousemove", "ur-pt", (e) => { map.getCanvas().style.cursor = "pointer"; hover(fromReport(e.features[0].properties.id)); });
    map.on("mouseleave", "ur-pt", () => { map.getCanvas().style.cursor = ""; later(); });
    map.on("mousemove", "ur-cl", (e) => {
      map.getCanvas().style.cursor = "pointer";
      const ids = leaves.get(e.features[0].properties.cluster_id) || [];
      hover({ keys: [...new Set(ids.map((i) => byId.get(i).properties.row).filter(Boolean))], ids, card: null });
    });
    map.on("mouseleave", "ur-cl", () => { map.getCanvas().style.cursor = ""; later(); });
    map.on("mousemove", "ul-cl-hit", (e) => {
      if (map.queryRenderedFeatures(e.point, { layers: ["ur-pt", "ur-cl"] }).length) return;
      map.getCanvas().style.cursor = "pointer";
      hover({ keys: [e.features[0].properties.row], ids: [], card: null });
    });
    map.on("mouseleave", "ul-cl-hit", () => { map.getCanvas().style.cursor = ""; later(); });
    map.on("click", (e) => {
      const f = map.queryRenderedFeatures(e.point, { layers: ["ur-pt", "ur-cl"] })[0];
      if (!f) { close(); return; }
      if (f.layer.id === "ur-cl") {
        close();
        map.getSource("ur").getClusterExpansionZoom(f.properties.cluster_id)
          .then((z) => map.easeTo({ center: f.geometry.coordinates, zoom: Math.min(z, map.getMaxZoom()) }));
        return;
      }
      pinned = fromReport(f.properties.id);    // the card has a toggle and a link: a click (a tap) pins it
      hovered = null;
      apply();
    });
    map.on("move", place);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && (pinned || hovered)) close(); });
    document.addEventListener("click", (e) => {
      if (pinned && !wrap.contains(e.target) && !sheet.contains(e.target) && !(list && list.contains(e.target))) close();
    });
    const wire = (e, make) => {
      e.addEventListener("mouseenter", () => hover(make()));
      e.addEventListener("mouseleave", later);
      e.addEventListener("focus", () => hover(make()));
      e.addEventListener("blur", later);
    };
    if (list) list.querySelectorAll("li[data-row]").forEach((li) => wire(li.firstElementChild, () => fromRow(li.dataset.row)));
    Object.entries(mark).forEach(([k, e]) => wire(e, () => ({ keys: [k], ids: [], card: null })));

    if (el.dataset.name) map.once("idle", () => osmStreet(map, el.dataset.name));
  }

  // RÚIAN's line of a street can run along neighbouring roads (Benešovo náměstí goes round the
  // whole block), so the street is the base map's road of that name where OpenStreetMap knows
  // it, RÚIAN's line only where it doesn't (the same in cisteni.js)
  function osmStreet(map, name) {
    const fold = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
    const roads = map.querySourceFeatures("protomaps", { sourceLayer: "roads" })
      .filter((f) => f.properties.name && fold(f.properties.name) === fold(name) && /LineString/.test(f.geometry.type));
    if (!roads.length) return;
    const lines = roads.flatMap((f) => (f.geometry.type === "LineString" ? [f.geometry.coordinates] : f.geometry.coordinates));
    map.getSource("ul-street").setData({ type: "Feature", geometry: { type: "MultiLineString", coordinates: lines }, properties: {} });
    const b = new maplibregl.LngLatBounds();
    lines.forEach((l) => l.forEach((c) => b.extend(c)));
    data.cleaning.features.filter((f) => !f.properties.past).forEach((f) => walk(b, f.geometry.coordinates));
    map.fitBounds(b, { padding: 40, maxZoom: 17, duration: 0 });
  }
})();
