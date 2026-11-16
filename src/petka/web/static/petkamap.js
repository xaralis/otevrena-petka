// The portal's one map (self-hosted MapLibre + PMTiles): every map page (aktualne.js, cisteni.js,
// podnety.js, ulice.js) creates its map and layers here and only says what it shows and how its
// list points at it. Tooltips and cards are maptip.js.
//   create(el, opts)        the map in el (data-style, data-tiles): style, PMTiles, controls, Czech
//                           texts, cooperative gestures, start bounds; resolves on load
//   bounds(things), fit()   bounds of features / geometries / [lng, lat] points; fit never fits
//                           empty bounds
//   belowLabels(map, ids)   our lines under the base map's street and place names
//   street(map, opts)       one street: the base map's road of that name (OpenStreetMap), RÚIAN's
//                           line where OpenStreetMap doesn't know it
//   cleaning(map, opts)     cleaned stretches and areas: scheme "grey" (grey, ink while lit; the
//                           front page and the street page) or "props" (each feature's own
//                           color/width/dash, ink while lit; the cleaning pages)
//   reports(map, opts)      podněty as points and clusters (canvas images, the red hatch), a ring
//                           to outline some, which point or cluster shows each report now, and
//                           the report's card
//   marks(map, list, opts)  úřední deska notices: hatched square = traffic, white = the kind's icon
//   anchors(map, list)      where a cleaning's tooltip hangs: zero size, or an area's marker
//   linker(apply, opts)     one hover / focus / pin controller: pointing shows a state, a click
//                           or a tap pins it, Escape and a click elsewhere unpin; apply(state)
//                           draws it (state = what is pointed at, else what is pinned, else null)
window.petkaMap = (function () {
  const INK = "#191c1f", RED = "#de091c", PINK = "#f4a3aa", GREY = "#7d838b";
  const TOWN = [[15.738, 49.996], [15.812, 50.043]];
  const LOCALE = {
    "CooperativeGesturesHandler.WindowsHelpText": "Mapu přiblížíte s klávesou Ctrl a kolečkem myši",
    "CooperativeGesturesHandler.MacHelpText": "Mapu přiblížíte s klávesou ⌘ a kolečkem myši",
    "CooperativeGesturesHandler.MobileHelpText": "Mapou posunete dvěma prsty",
    "NavigationControl.ZoomIn": "Přiblížit", "NavigationControl.ZoomOut": "Oddálit",
  };
  const ok = () => !!(window.maplibregl && window.pmtiles);
  let protocol = null;
  const narrow = () => window.matchMedia("(max-width: 900px)").matches;
  const fold = (t) => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

  // --- the map ----------------------------------------------------------------------------------
  // opts: bounds (start, default the town), fitBoundsOptions, maxBounds (null: none), minZoom,
  // maxZoom, cooperative (default true), controls ("top-right"), font (wait for Bricolage, the
  // clusters' canvas text needs it)
  function create(el, opts = {}) {
    if (!protocol) { protocol = new pmtiles.Protocol(); maplibregl.addProtocol("pmtiles", protocol.tile); }
    const abs = (u) => location.origin + u;
    const font = opts.font && document.fonts && document.fonts.load
      ? document.fonts.load('800 12px "Bricolage Grotesque"').catch(() => {}) : Promise.resolve();
    return Promise.all([fetch(el.dataset.style).then((r) => r.json()), font]).then(([s]) => {
      s.sprite = abs(s.sprite);
      s.glyphs = abs(s.glyphs);
      s.sources.protomaps.url = "pmtiles://" + abs(el.dataset.tiles);
      const map = new maplibregl.Map({
        container: el, style: s, bounds: opts.bounds || TOWN, fitBoundsOptions: opts.fitBoundsOptions,
        maxBounds: opts.maxBounds === null ? undefined : opts.maxBounds || [[15.64, 49.95], [15.90, 50.09]],
        minZoom: opts.minZoom || 11, maxZoom: opts.maxZoom || 18.5, attributionControl: { compact: true },
        cooperativeGestures: opts.cooperative !== false, locale: LOCALE,
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), opts.controls || "top-right");
      return new Promise((done) => map.on("load", () => done(map)));
    });
  }

  function bounds(things) {
    const b = new maplibregl.LngLatBounds();
    const walk = (c) => { if (typeof c[0] === "number") b.extend(c); else c.forEach(walk); };
    (things || []).forEach((t) => {
      if (!t) return;
      if (Array.isArray(t)) walk(t);
      else if (t.geometry) { if (t.geometry.coordinates) walk(t.geometry.coordinates); }
      else if (t.coordinates) walk(t.coordinates);
      else if (t.lng !== undefined) b.extend([t.lng, t.lat]);
    });
    return b.isEmpty() ? null : b;
  }
  function fit(map, things, opts = {}) {
    const b = things instanceof maplibregl.LngLatBounds ? things : bounds(things);
    if (b) map.fitBounds(b, { padding: 40, maxZoom: 17, duration: 0, ...opts });
    return !!b;
  }
  function belowLabels(map, ids, own = /^(ak|cl|pd|ul|ur|pm)-/) {
    const labels = map.getStyle().layers.find((l) => l.type === "symbol" && !own.test(l.id));
    if (labels) ids.forEach((id) => map.getLayer(id) && map.moveLayer(id, labels.id));
  }
  const width = (k) => ["interpolate", ["linear"], ["zoom"], 12, 4 + k, 15, 6 + k, 18, 9 + k];
  const round = { "line-cap": "round", "line-join": "round" };

  // --- one street ---------------------------------------------------------------------------
  // opts: id, geometry (RÚIAN), name, paint (of the line), casing (a white line under it, px
  // more), refit(bounds) when the base map's road is found (default: fit to it)
  // RÚIAN's line of a street can run along neighbouring roads (Benešovo náměstí goes round the
  // whole block), so the street is the base map's road of that name where it has one
  function street(map, opts) {
    const id = opts.id || "pm-street";
    map.addSource(id, { type: "geojson", data: { type: "Feature", geometry: opts.geometry || { type: "MultiLineString", coordinates: [] }, properties: {} } });
    if (opts.casing) map.addLayer({ id: id + "-case", type: "line", source: id, layout: round,
                                    paint: { "line-color": "#ffffff", "line-width": opts.casing } });
    map.addLayer({ id, type: "line", source: id, layout: round, paint: opts.paint });
    if (opts.name) map.once("idle", () => {
      const want = fold(opts.name);
      const roads = map.querySourceFeatures("protomaps", { sourceLayer: "roads" })
        .filter((f) => f.properties.name && fold(f.properties.name) === want && /LineString/.test(f.geometry.type));
      if (!roads.length) return;
      const lines = roads.flatMap((f) => (f.geometry.type === "LineString" ? [f.geometry.coordinates] : f.geometry.coordinates));
      const g = { type: "MultiLineString", coordinates: lines };
      map.getSource(id).setData({ type: "Feature", geometry: g, properties: {} });
      (opts.refit || ((b) => fit(map, b)))(bounds([g]));
    });
    return [id + "-case", id].filter((x) => map.getLayer(x));
  }

  // --- cleaned stretches and areas ----------------------------------------------------------
  // opts: id, data (FeatureCollection; properties `area` true for a polygon), scheme ("grey" or
  // "props"), by (the property lit() matches, default "key"), show (an extra filter of what is
  // drawn when not lit, e.g. only upcoming), hit (px of an invisible line to point at, 0 none),
  // fade (the grey lines fade in), areas ("outline": a thin dashed line only while lit, the
  // overviews; "fill": grey dashed outline always, filled ink while lit, the street page)
  // returns {lit(values), layers, hit}
  function cleaning(map, opts) {
    const id = opts.id || "pm-cl", by = opts.by || "key";
    const isArea = ["match", ["geometry-type"], ["Polygon", "MultiPolygon"], true, false];
    const line = ["!", isArea];
    const show = opts.show || true;
    const lit = (vs) => ["in", ["get", by], ["literal", vs]];
    map.addSource(id, { type: "geojson", data: opts.data, ...(opts.scheme === "props" ? { promoteId: by } : {}) });
    const ids = [];
    const add = (l) => { map.addLayer({ source: id, ...l }); ids.push(l.id); };
    if (opts.areas === "fill") {
      add({ id: id + "-ar-on", type: "fill", filter: ["all", isArea, lit([])], paint: { "fill-color": INK, "fill-opacity": 0.25 } });
      add({ id: id + "-ar", type: "line", filter: ["all", isArea, show], paint: { "line-color": GREY, "line-width": 1.5, "line-dasharray": [2, 2] } });
      add({ id: id + "-ar-on-l", type: "line", filter: ["all", isArea, lit([])], paint: { "line-color": INK, "line-width": 2.5 } });
    } else {
      add({ id: id + "-ar-on-l", type: "line", filter: ["all", isArea, lit([])], paint: { "line-color": INK, "line-width": 1.5, "line-dasharray": [2, 2] } });
    }
    if (opts.scheme === "props") {
      // each feature's color, width (grows with zoom) and dash; the one lit (feature-state on) ink
      const w = (extra) => ["interpolate", ["linear"], ["zoom"],
        ...[[12, 0.75], [15, 1], [18, 1.8]].flatMap(([z, k]) => [z, ["*", ["+", ["get", "width"], extra], k]])];
      const color = ["case", ["boolean", ["feature-state", "on"], false], INK, ["get", "color"]];
      add({ id: id + "-case", type: "line", filter: ["all", line, show], layout: round, paint: { "line-color": "#ffffff", "line-width": w(3) } });
      add({ id: id + "-line", type: "line", filter: ["all", line, show, ["==", ["get", "dash"], false]], layout: round,
            paint: { "line-color": color, "line-width": w(0) } });
      add({ id: id + "-line-d", type: "line", filter: ["all", line, show, ["==", ["get", "dash"], true]], layout: { "line-join": "round" },
            paint: { "line-color": color, "line-width": w(0), "line-dasharray": [1.5, 1.2] } });
    } else {
      const fade = opts.fade ? { "line-opacity": 0, "line-opacity-transition": { duration: 500, delay: 0 } } : {};
      add({ id: id + "-case", type: "line", filter: ["all", line, show], layout: round, paint: { "line-color": "#ffffff", "line-width": width(4), ...fade } });
      add({ id: id + "-line", type: "line", filter: ["all", line, show], layout: round, paint: { "line-color": GREY, "line-width": width(0), ...fade } });
      add({ id: id + "-on-case", type: "line", filter: ["all", line, lit([])], layout: round, paint: { "line-color": "#ffffff", "line-width": width(4) } });
      add({ id: id + "-on", type: "line", filter: ["all", line, lit([])], layout: round, paint: { "line-color": INK, "line-width": width(0) } });
      if (opts.fade) setTimeout(() => [id + "-case", id + "-line"].forEach((l) => map.setPaintProperty(l, "line-opacity", 1)), 400);
    }
    belowLabels(map, ids);
    let hit = null;
    if (opts.hit) {
      hit = id + "-hit";
      map.addLayer({ id: hit, source: id, type: "line", filter: ["all", line, show], layout: round,
                     paint: { "line-color": INK, "line-opacity": 0, "line-width": opts.hit } });
    }
    let on = [];
    return {
      layers: ids, hit,
      lit(vs) {
        vs = vs || [];
        if (opts.scheme === "props") {
          on.forEach((k) => map.setFeatureState({ source: id, id: k }, { on: false }));
          vs.forEach((k) => map.setFeatureState({ source: id, id: k }, { on: true }));
          on = vs;
        } else {
          [id + "-on-case", id + "-on"].forEach((l) => map.setFilter(l, ["all", line, lit(vs)]));
          if (map.getLayer(id + "-ar-on")) map.setFilter(id + "-ar-on", ["all", isArea, lit(vs)]);
        }
        map.setFilter(id + "-ar-on-l", ["all", isArea, lit(vs)]);
      },
    };
  }
  // the cleaning overview's colours by the nearest date: ≤ 7 days red, ≤ 14 ink, later grey;
  // an approximate place dashed; the nearest drawn on top
  function colourByDate(fc, today) {
    const t0 = Date.parse(today);
    fc.features.forEach((f) => {
      const p = f.properties, days = (Date.parse(p.next) - t0) / 864e5;
      const [color, w, rank] = days <= 7 ? [RED, 5, 3] : days <= 14 ? [INK, 4, 2] : ["#8a9097", 3, 1];
      Object.assign(p, { color, width: w, rank, dash: p.status === "approx" || p.status === "partial" });
    });
    fc.features.sort((a, b) => a.properties.rank - b.properties.rank);
  }

  // --- podněty --------------------------------------------------------------------------------
  // the hatch of .pending-alert, at pixelRatio 2: pink with red stripes 3 px wide every 6 px
  function hatch(g, size) {
    g.fillStyle = PINK; g.fillRect(0, 0, size, size);
    g.strokeStyle = RED; g.lineWidth = 6;
    for (let x = -size; x < 2 * size; x += 12) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x + size, size); g.stroke(); }
  }
  function canvas(css) {
    const c = document.createElement("canvas");
    c.width = c.height = css * 2;
    return c.getContext("2d");
  }
  // one report: a 14 px circle with a 2 px ink border, white or hatched
  function point(waiting) {
    const g = canvas(18), m = 18;
    g.save(); g.beginPath(); g.arc(m, m, 14, 0, 2 * Math.PI); g.clip();
    if (waiting) hatch(g, 36); else { g.fillStyle = "#fff"; g.fill(); }
    g.restore();
    g.beginPath(); g.arc(m, m, 13, 0, 2 * Math.PI); g.lineWidth = 4; g.strokeStyle = INK; g.stroke();
    return g.getImageData(0, 0, 36, 36);
  }
  // a cluster of n, w of them waiting: radius 10 + 1.7 √n px, the hatched wedge from twelve
  // o'clock, an ink ring, a white middle with the count
  const radius = (n) => 10 + 1.7 * Math.sqrt(n);
  function cluster(n, w) {
    const r = radius(n), css = Math.ceil(2 * r + 4), g = canvas(css), m = css, R = 2 * r;
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

  // words of the card
  const plural = (n, one, few, many) => (n === 1 ? one : n >= 2 && n <= 4 ? few : many);
  const thisYear = new Date().getFullYear();
  function dm(iso) { const [y, mo, d] = iso.slice(0, 10).split("-").map(Number); return `${d}. ${mo}.` + (y !== thisYear ? ` ${y}` : ""); }
  function when(iso) {
    const h = +iso.slice(11, 13), mi = iso.slice(14, 16);
    return `${dm(iso)} ${[2, 3, 4, 12, 13, 14, 20, 21, 22, 23].includes(h) ? "ve" : "v"} ${h}:${mi}`;
  }
  const DETAIL = "https://amg.dejtip.eu/pardubice/?id=";
  // the card: Dej Tip's own status word (red while it waits), how long it waits a fact of its own.
  // p = a stats.points feature's properties: id, o, w, c, s, t, a, d, p, wd
  function reportCard(p, onresize) {
    const facts = [["nahlášeno", when(p.t), "ak-f-date"]];
    if (p.a) facts.push(["odpověď úřadu", when(p.a), "ak-f-date"]);
    facts.push(["stav", p.w, p.o === "ceka" ? "st-no" : ""]);
    if (p.o === "ceka") { const n = p.wd || 0; facts.push(["čeká", n < 1 ? "od dneška" : `${n} ${plural(n, "den", "dny", "dní")}`]); }
    return window.mapTip.card({
      photo: p.p, alt: `Fotka z podnětu: ${p.c}${p.s ? ", " + p.s : ""}`, title: p.c, place: p.s, text: p.d,
      facts, href: DETAIL + p.id, link: "Otevřít na Dej Tipu",
    }, onresize);
  }

  // opts: id, data (FeatureCollection of stats.points), wrap (the positioned box the card goes
  // in), sheet (where the card goes on phones; none: always over the map), owners (keep track
  // of which point or cluster shows each report). Returns {pt, cl, source, setData, ring,
  // owner, leaves, card: {show(id, at), hide(), place(), el, id}}
  function reports(map, opts) {
    const id = opts.id || "pm-rep", empty = { type: "FeatureCollection", features: [] };
    let feats = opts.data.features, byId = new Map(feats.map((f) => [f.properties.id, f]));
    map.addImage(id + "-pt", point(false), { pixelRatio: 2 });
    map.addImage(id + "-pt-w", point(true), { pixelRatio: 2 });
    const re = new RegExp("^" + id + "-c-(\\d+)-(\\d+)$");
    map.on("styleimagemissing", (e) => {
      const m = re.exec(e.id);
      if (m && !map.hasImage(e.id)) map.addImage(e.id, cluster(+m[1], +m[2]), { pixelRatio: 2 });
    });
    map.addSource(id, { type: "geojson", data: opts.data, cluster: true, clusterRadius: 44, clusterMaxZoom: 16,
                        clusterProperties: { waiting: ["+", ["case", ["==", ["get", "o"], "ceka"], 1, 0]] } });
    map.addSource(id + "-hl", { type: "geojson", data: empty });
    const pt = id + "-pt", cl = id + "-cl";
    const solo = { "icon-allow-overlap": true, "icon-ignore-placement": true };
    map.addLayer({ id: pt, type: "symbol", source: id, filter: ["!", ["has", "point_count"]],
                   layout: { ...solo, "icon-image": ["case", ["==", ["get", "o"], "ceka"], id + "-pt-w", id + "-pt"],
                             "symbol-sort-key": ["case", ["==", ["get", "o"], "ceka"], 1, 0] } });
    map.addLayer({ id: cl, type: "symbol", source: id, filter: ["has", "point_count"],
                   layout: { ...solo, "icon-image": ["concat", id + "-c-", ["to-string", ["get", "point_count"]], "-",
                                                     ["to-string", ["get", "waiting"]]],
                             "symbol-sort-key": ["get", "point_count"] } });
    map.addLayer({ id: id + "-ring", type: "circle", source: id + "-hl",
                   paint: { "circle-radius": ["get", "r"], "circle-opacity": 0, "circle-stroke-color": INK, "circle-stroke-width": 3 } });

    // which point or cluster shows each report, recounted when the map settles
    let owner = new Map(), leaves = new Map(), settled = false;
    const listeners = [];
    function recount() {
      const next = new Map(), lv = new Map(), waits = [];
      map.queryRenderedFeatures({ layers: [pt] }).forEach((f) =>
        next.set(f.properties.id, { at: f.geometry.coordinates, r: 12, key: "p" + f.properties.id }));
      map.queryRenderedFeatures({ layers: [cl] }).forEach((f) => {
        const cid = f.properties.cluster_id;
        if (lv.has(cid)) return;
        lv.set(cid, []);
        waits.push(map.getSource(id).getClusterLeaves(cid, Infinity, 0).then((fs) => {
          const o = { at: f.geometry.coordinates, r: radius(f.properties.point_count) + 3, key: "c" + cid };
          fs.forEach((x) => { next.set(x.properties.id, o); lv.get(cid).push(x.properties.id); });
        }).catch(() => {}));
      });
      Promise.all(waits).then(() => { owner = next; leaves = lv; listeners.forEach((f) => f()); });
    }
    if (opts.owners) {
      map.on("idle", () => { if (!settled) { settled = true; recount(); } });
      map.on("movestart", () => (settled = false));
    }

    // the card, placed by the point (or the point's cluster); on phones in the sheet
    const card = { el: null, id: null };
    let resized = () => {};
    card.place = () => {
      if (!card.el) return;
      if (card.el.fit) card.el.fit();
      if (opts.sheet && narrow()) return;
      const o = owner.get(card.id), at = o ? o.at : byId.get(card.id).geometry.coordinates;
      const p = map.project(at), el = map.getContainer();
      if (opts.closeOutside && (p.x < -10 || p.y < -10 || p.x > el.clientWidth + 10 || p.y > el.clientHeight + 10)) { opts.closeOutside(); return; }
      window.mapTip.place(card.el, p.x, p.y, el.clientWidth, el.clientHeight);
    };
    card.show = (rid, hooks = {}) => {
      if (rid === card.id && card.el) { card.place(); return card.el; }
      card.hide();
      card.id = rid;
      card.el = reportCard(byId.get(rid).properties, () => card.place());
      if (hooks.enter) card.el.addEventListener("mouseenter", hooks.enter);
      if (hooks.leave) card.el.addEventListener("mouseleave", hooks.leave);
      if (opts.sheet && narrow()) opts.sheet.replaceChildren(card.el); else opts.wrap.appendChild(card.el);
      card.el.classList.add("on");       // shown first: a hidden card measures 0 wide and place() would let it run off the map
      card.place();
      return card.el;
    };
    card.hide = () => { if (card.el) card.el.remove(); card.el = null; card.id = null; };
    map.on("move", () => card.place());
    resized = card.place;

    return {
      pt, cl, source: id, card, byId: () => byId,
      setData(fc) { feats = fc.features; byId = new Map(feats.map((f) => [f.properties.id, f])); map.getSource(id).setData(fc); },
      // outline: [{at, r, key}] (owner()) or features (their own point, 11 px)
      ring(items) {
        const seen = new Map();
        items.forEach((o) => { if (o) seen.set(o.key || o.properties.id, o.at ? o : { at: o.geometry.coordinates, r: 11 }); });
        map.getSource(id + "-hl").setData({ type: "FeatureCollection", features: Array.from(seen.values()).map((o) =>
          ({ type: "Feature", geometry: { type: "Point", coordinates: o.at }, properties: { r: o.r } })) });
      },
      owner: (rid) => owner.get(rid), leaves: (cid) => leaves.get(cid) || [],
      onCount(f) { listeners.push(f); },
      zoomInto(f) {
        map.getSource(id).getClusterExpansionZoom(f.properties.cluster_id)
          .then((z) => map.easeTo({ center: f.geometry.coordinates, zoom: Math.min(z, map.getMaxZoom()) }));
      },
    };
  }

  // --- markers ------------------------------------------------------------------------------
  // úřední deska notices: [{id, nid, kind, traffic, label, lng, lat, title, what, when}]; a marker
  // is a link to its notice. opts: icons (the sprite's URL), animate (drop in one by one),
  // key (the property the result is keyed by, default id). Returns {key: element}
  function marks(map, list, opts = {}) {
    const out = {}, NS = "http://www.w3.org/2000/svg";
    list.forEach((m, i) => {
      const e = document.createElement(m.href || m.nid ? "a" : "span");
      if (m.href) e.href = m.href;                  // a closure from NDIC: its place on the Uzavírky page
      else if (m.nid) e.href = "/radnice/uredni-deska/" + encodeURIComponent(m.nid);
      e.className = "ak-mk" + (m.traffic ? " ak-mk-t" : "");
      e.tabIndex = 0;
      e.setAttribute("aria-label", m.label);
      if (opts.animate) e.style.animationDelay = (0.25 + 0.06 * i).toFixed(2) + "s";
      const box = document.createElement("i");
      if (!m.traffic) {
        const svg = document.createElementNS(NS, "svg"), use = document.createElementNS(NS, "use");
        svg.setAttribute("width", "19"); svg.setAttribute("height", "19"); svg.setAttribute("aria-hidden", "true");
        use.setAttribute("href", opts.icons + "#" + m.kind);
        svg.appendChild(use);
        box.appendChild(svg);
      }
      e.append(box, window.mapTip.make(m.title, m.what, m.when));
      out[m[opts.key || "id"]] = e;
      new maplibregl.Marker({ element: e }).setLngLat([m.lng, m.lat]).addTo(map);
    });
    return out;
  }
  // a cleaning's tooltip: [{lng, lat, title, what, when, label, href, area, strip}]; a zero-size
  // anchor (.ak-cla) or an area's marker (a dashed square, `strip` its bottom edge). opts.key
  // as for marks, opts.hidden: not focusable (the list carries it). Returns {key: element}
  function anchors(map, list, opts = {}) {
    const out = {};
    list.forEach((a) => {
      const e = document.createElement(a.href ? "a" : "span");
      if (a.href) e.href = a.href;
      e.className = a.area ? "ak-mk ak-mk-a" : "ak-cla";
      if (opts.hidden) e.setAttribute("aria-hidden", "true");
      else { e.tabIndex = 0; e.setAttribute("aria-label", a.label); }
      if (a.area) {
        const i = window.mapTip.area();
        if (a.strip) i.style.setProperty("--strip", a.strip);
        e.appendChild(i);
      }
      e.appendChild(window.mapTip.make(a.title, a.what, a.when));
      out[a[opts.key || "id"]] = e;
      new maplibregl.Marker({ element: e }).setLngLat([a.lng, a.lat]).addTo(map);
    });
    return out;
  }
  // light elements of a state: .on, the tooltips of markers turned away from the map's edge
  function light(els, edge, box) {
    els.forEach((e) => {
      if (!e) return;
      e.classList.add("on");
      if (e.matches(".ak-mk, .ak-cla")) window.mapTip.side(e, edge, box);
    });
  }

  // --- pointing ---------------------------------------------------------------------------------
  // apply(state) draws a state (null: nothing). opts: same(a, b) (one state, for "a second tap
  // opens"), delay (ms before a state pointed away from goes, so a card can be reached), stick (pointing
  // does nothing while something is pinned), within
  // (elements whose clicks don't unpin). Returns {hover, leave, pin, close, wire, pinned, sameAsPinned}
  function linker(apply, opts = {}) {
    let hovered = null, pinned = null, timer = null;
    const same = opts.same || ((a, b) => a === b);
    const draw = () => apply(hovered || pinned);
    const api = {
      get pinned() { return pinned; },
      hover(st) { if (opts.stick && pinned) return; clearTimeout(timer); hovered = st; draw(); },
      leave() {
        if (opts.stick && pinned) return;
        clearTimeout(timer);
        if (opts.delay) timer = setTimeout(() => { hovered = null; draw(); }, opts.delay);
        else { hovered = null; draw(); }
      },
      keep() { clearTimeout(timer); },
      pin(st, toggle) { clearTimeout(timer); hovered = null; pinned = toggle && pinned && same(st, pinned) ? null : st; draw(); },
      close() { clearTimeout(timer); hovered = pinned = null; draw(); },
      redraw: draw,
      sameAsPinned: (st) => !!(pinned && st && same(st, pinned)),
      // an element (a row, a marker) that points at make()'s state; a link with `opens` opens
      // at once on wide screens and with a second tap on phones, otherwise a click pins
      wire(e, make, w = {}) {
        e.addEventListener("mouseenter", () => api.hover(make()));
        e.addEventListener("mouseleave", api.leave);
        e.addEventListener(w.within ? "focusin" : "focus", () => api.hover(make()));
        e.addEventListener(w.within ? "focusout" : "blur", api.leave);
        if (w.pins) e.addEventListener("click", (ev) => {
          ev.stopPropagation();
          const st = make();
          if (e.href && (!narrow() || api.sameAsPinned(st))) return;
          ev.preventDefault();
          api.pin(st, true);
        });
      },
    };
    if (opts.escape !== false) document.addEventListener("keydown", (e) => { if (e.key === "Escape" && (pinned || hovered)) api.close(); });
    if (opts.within) document.addEventListener("click", (e) => {
      if (pinned && !opts.within().some((x) => x && x.contains(e.target))) api.close();
    });
    return api;
  }

  return { INK, GREY, RED, ok, narrow, fold, create, bounds, fit, belowLabels, street, cleaning, colourByDate,
           reports, reportCard, radius, plural, dm, when, DETAIL, marks, anchors, light, linker };
})();
