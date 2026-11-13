// Čištění ulic: the maps (self-hosted MapLibre + PMTiles, like map.js) and the calendar picker.
// <div data-cl-map="all" data-src="/api/v1/cisteni" data-today="YYYY-MM-DD" data-anchors="id">
// colours the obvod's places by their next cleaning and behaves like the front page's map
// (aktualne.js): pointing at a stretch inks it and shows its tooltip (maptip.js) on a focusable
// zero-size anchor, a click opens its street (on phones the second tap), and the rows of
// „Příštích 7 dní“ ([data-cl-key]) light up with their stretches both ways.
// On the overview an area (a parkoviště or a vnitroblok, a polygon whose shape is our estimate)
// is a marker at a point inside (window.mapTip.area), the same family as the front page's; its
// outline shows as a thin dashed line only while the marker (or its row) is pointed at.
// <div data-cl-map="street" data-inline="id"> shows one street: its RÚIAN line in ink and,
// thicker, the stretches still to be cleaned on it; no tooltips (the dates are in the table).
// The picker remembers its streets in localStorage; without JS the form goes to /verejny-prostor/blokove-cisteni/kalendar.
(function () {
  const RED = "#de091c", INK = "#191c1f", GREY = "#8a9097";

  // --- maps -----------------------------------------------------------------------------------
  const maps = document.querySelectorAll("[data-cl-map]");
  if (maps.length && window.maplibregl && window.pmtiles) {
    const protocol = new pmtiles.Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
    maps.forEach(setup);
  }

  function setup(el) {
    const all = el.dataset.clMap === "all";
    const abs = (u) => location.origin + u;
    const style = fetch(el.dataset.style).then((r) => r.json()).then((s) => {
      s.sprite = abs(s.sprite);
      s.glyphs = abs(s.glyphs);
      s.sources.protomaps.url = "pmtiles://" + abs(el.dataset.tiles);
      return s;
    });
    const data = el.dataset.src
      ? fetch(el.dataset.src).then((r) => r.json())
      : Promise.resolve(JSON.parse(document.getElementById(el.dataset.inline).textContent));
    style.then((s) => {
      const map = new maplibregl.Map({
        container: el, style: s,
        bounds: [[15.738, 49.996], [15.812, 50.043]], maxBounds: [[15.64, 49.95], [15.90, 50.09]],
        minZoom: 11, maxZoom: 18.5, attributionControl: { compact: true }, cooperativeGestures: !all,
        locale: {
          "CooperativeGesturesHandler.WindowsHelpText": "Mapu přiblížíte s klávesou Ctrl a kolečkem myši",
          "CooperativeGesturesHandler.MacHelpText": "Mapu přiblížíte s klávesou ⌘ a kolečkem myši",
          "CooperativeGesturesHandler.MobileHelpText": "Mapou posunete dvěma prsty",
          "NavigationControl.ZoomIn": "Přiblížit", "NavigationControl.ZoomOut": "Oddálit",
        },
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      map.on("load", async () => {
        const fc = await data;
        // the overview shows only what is still to come this year (the API is asked from today)
        fc.features = fc.features.filter((f) => f.geometry && (!all || f.properties.next));
        if (all) colour(fc, el.dataset.today); else street(fc);
        const lines = fc.features.filter((f) => !/Polygon/.test(f.geometry.type));
        const bounds = fc.features;
        map.addSource("cl", { type: "geojson", data: { ...fc, features: lines }, promoteId: "key" });
        // the areas: on the overview their outlines only for the keys pointed at
        map.addSource("cl-areas", { type: "geojson", data: { ...fc, features: fc.features.filter((f) => /Polygon/.test(f.geometry.type)) } });
        const line = ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false];
        // widths grow with zoom; a white casing keeps the stretches crisp over the base map
        const w = (extra) => ["interpolate", ["linear"], ["zoom"],
          ...[[12, 0.75], [15, 1], [18, 1.8]].flatMap(([z, k]) => [z, ["*", ["+", ["get", "width"], extra], k]])];
        const solid = ["==", ["get", "dash"], false], dashed = ["==", ["get", "dash"], true];
        // the stretch pointed at (feature-state "on") turns ink, the same width and dashes
        const color = ["case", ["boolean", ["feature-state", "on"], false], INK, ["get", "color"]];
        map.addLayer({ id: "cl-area", type: "line", source: "cl-areas", filter: ["in", ["get", "key"], ["literal", []]],
                       paint: { "line-color": INK, "line-width": 1.5, "line-dasharray": [2, 2] } });
        map.addLayer({ id: "cl-case", type: "line", source: "cl", filter: line,
                       layout: { "line-cap": "round", "line-join": "round" },
                       paint: { "line-color": "#ffffff", "line-width": w(3) } });
        map.addLayer({ id: "cl-line", type: "line", source: "cl", filter: ["all", line, solid],
                       layout: { "line-cap": "round", "line-join": "round" },
                       paint: { "line-color": color, "line-width": w(0) } });
        map.addLayer({ id: "cl-line-d", type: "line", source: "cl", filter: ["all", line, dashed],
                       layout: { "line-join": "round" },
                       paint: { "line-color": color, "line-width": w(0), "line-dasharray": [1.5, 1.2] } });
        // keep the base map's street and place names above our lines
        const labels = map.getStyle().layers.find((l) => l.type === "symbol");
        if (labels) ["cl-area", "cl-case", "cl-line", "cl-line-d"]
          .forEach((id) => map.getLayer(id) && map.moveLayer(id, labels.id));
        const b = new maplibregl.LngLatBounds();
        const walk = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(walk));
        bounds.forEach((f) => walk(f.geometry.coordinates));
        if (!b.isEmpty()) map.fitBounds(b, { padding: all ? 20 : 40, maxZoom: 17, duration: 0 });
        if (!all && el.dataset.name) map.once("idle", () => osmStreet(map, el.dataset.name, fc));
        if (all) {
          // a wide invisible line over the stretches makes them easy to point at
          map.addLayer({ id: "cl-hit", type: "line", source: "cl", filter: line,
                         paint: { "line-color": INK, "line-opacity": 0, "line-width": 16 } });
          tips(map, el, fc);
        }
      });
    });
  }

  // nearest date: ≤ 7 days red, ≤ 14 ink, later this year grey; approximate dashed
  function colour(fc, today) {
    const t0 = Date.parse(today);
    fc.features.forEach((f) => {
      const p = f.properties, days = (Date.parse(p.next) - t0) / 864e5;
      const [color, width, rank] = days <= 7 ? [RED, 5, 3] : days <= 14 ? [INK, 4, 2] : [GREY, 3, 1];
      Object.assign(p, { color, width, rank, dash: p.status === "approx" || p.status === "partial" });
    });
    fc.features.sort((a, b) => a.properties.rank - b.properties.rank);   // the nearest drawn on top
  }

  // RÚIAN's line of a street can run along neighbouring roads (Benešovo náměstí is drawn round
  // the whole block), so the street is the base map's road of that name where OpenStreetMap
  // knows it, RÚIAN's line only where it doesn't
  function osmStreet(map, name, fc) {
    const fold = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
    const want = fold(name);
    const roads = map.querySourceFeatures("protomaps", { sourceLayer: "roads" })
      .filter((f) => f.properties.name && fold(f.properties.name) === want
                     && /LineString/.test(f.geometry.type));
    if (!roads.length) return;
    const lines = roads.flatMap((f) => (f.geometry.type === "LineString" ? [f.geometry.coordinates] : f.geometry.coordinates));
    const own = { type: "Feature", geometry: { type: "MultiLineString", coordinates: lines },
                  properties: { kind: "street", color: INK, width: 3, dash: false, key: "street" } };
    const rest = fc.features.filter((f) => f.properties.kind !== "street" && !/Polygon/.test(f.geometry.type));
    map.getSource("cl").setData({ type: "FeatureCollection", features: [own, ...rest] });
    const b = new maplibregl.LngLatBounds();
    lines.forEach((l) => l.forEach((c) => b.extend(c)));
    rest.forEach((f) => (function walk(c) { typeof c[0] === "number" ? b.extend(c) : c.forEach(walk); })(f.geometry.coordinates));
    map.fitBounds(b, { padding: 40, maxZoom: 17, duration: 0 });
  }

  // one street: its line in ink, the stretches still to be cleaned on it thicker
  function street(fc) {
    fc.features.forEach((f) => Object.assign(f.properties, { color: INK, width: f.properties.kind === "stretch" ? 6 : 3, dash: false }));
  }

  // the overview's tooltips and highlights, the same way as aktualne.js: pointing shows, a click
  // or a tap pins (phones have no hover), a click elsewhere on the map unpins
  function tips(map, el, fc) {
    const strip = {};
    fc.features.forEach((f) => (strip[f.properties.key] = f.properties.color));
    const narrow = () => window.matchMedia("(max-width: 900px)").matches;
    const src = document.getElementById(el.dataset.anchors);
    // a stretch: its places' keys (both sides of a street drawn as one line), its anchor, its rows
    const stretch = {}, of = {};
    (src ? JSON.parse(src.textContent) : []).forEach((a) => {
      const e = document.createElement(a.href ? "a" : "span");    // the street's cleaning page
      if (a.href) e.href = a.href;
      e.className = a.area ? "ak-mk ak-mk-a" : "ak-cla";
      e.tabIndex = 0;
      e.setAttribute("aria-label", a.label);
      if (a.area) {
        // an area's status: a strip on the marker's bottom edge in its stretches' colour
        const i = window.mapTip.area();
        i.style.setProperty("--strip", strip[a.keys[0]] || GREY);
        e.appendChild(i);
      }
      e.appendChild(window.mapTip.make(a.street, a.what, a.when));
      new maplibregl.Marker({ element: e }).setLngLat([a.lng, a.lat]).addTo(map);
      const s = stretch[a.keys[0]] = { keys: a.keys, anchor: e, rows: [] };
      a.keys.forEach((k) => (of[k] = s));
    });
    document.querySelectorAll("[data-cl-key]").forEach((r) => {
      const k = r.dataset.clKey;
      (of[k] ||= { keys: [k], anchor: null, rows: [] }).rows.push(r);   // a place not on the map lights only itself
    });

    let pinned = null, shown = null;
    function apply(s) {
      if (shown === s) return;
      if (shown) shown.keys.forEach((k) => map.setFeatureState({ source: "cl", id: k }, { on: false }));
      el.querySelectorAll(".ak-cla.on, .ak-mk.on").forEach((e) => e.classList.remove("on", "ak-l"));
      document.querySelectorAll("[data-cl-key].on").forEach((e) => e.classList.remove("on"));
      map.setFilter("cl-area", ["in", ["get", "key"], ["literal", s ? s.keys : []]]);
      shown = s;
      if (!s) return;
      s.keys.forEach((k) => map.setFeatureState({ source: "cl", id: k }, { on: true }));
      s.rows.forEach((r) => r.classList.add("on"));
      if (s.anchor) {
        s.anchor.classList.add("on");
        window.mapTip.side(s.anchor, el.getBoundingClientRect().right);
      }
    }
    const hover = (s) => apply(s || pinned);
    const pin = (s) => { pinned = s && s === pinned ? null : s; apply(pinned); };

    const layers = ["cl-hit"];
    const at = (p) => { const f = map.queryRenderedFeatures(p, { layers })[0]; return f ? of[f.properties.key] || null : null; };
    map.on("mousemove", (e) => {
      // a marker (an area) handles its own pointing
      if (e.originalEvent.target.closest && e.originalEvent.target.closest(".ak-mk")) return;
      const s = at(e.point);
      map.getCanvas().style.cursor = s ? "pointer" : "";
      hover(s);
    });
    map.on("mouseout", () => { map.getCanvas().style.cursor = ""; hover(null); });
    map.on("click", (e) => {
      if (e.originalEvent.target.closest && e.originalEvent.target.closest(".ak-cla, .ak-mk")) return;
      const s = at(e.point), a = s && s.anchor;
      // a stretch opens its street's page: at once on wide screens, on phones with a second tap
      if (a && a.href && (!narrow() || pinned === s)) { window.location.href = a.href; return; }
      pin(s);
    });
    new Set(Object.values(of)).forEach((s) => {
      const a = s.anchor;
      if (a) {
        a.addEventListener("mouseenter", () => hover(s));
        a.addEventListener("mouseleave", () => hover(null));
        a.addEventListener("focus", () => hover(s));
        a.addEventListener("blur", () => hover(null));
        a.addEventListener("click", (ev) => {
          ev.stopPropagation();
          if (a.href && (!narrow() || pinned === s)) return;
          ev.preventDefault();
          pin(s);
        });
      }
      // the rows stay plain links to their streets; pointing at one or focusing it shows its stretch
      s.rows.forEach((r) => {
        r.addEventListener("mouseenter", () => hover(s));
        r.addEventListener("mouseleave", () => hover(null));
        r.addEventListener("focusin", () => hover(s));
        r.addEventListener("focusout", () => hover(null));
      });
    });
  }

  // the phone's search field is narrow: a short placeholder
  const search = document.querySelector(".cl-search input");
  if (search && window.matchMedia("(max-width: 900px)").matches) search.placeholder = "Vaše ulice";

  // --- the calendar picker --------------------------------------------------------------------
  const form = document.querySelector("[data-cl-pick]");
  if (!form) return;
  const names = JSON.parse(document.getElementById("cl-names").textContent);   // {slug: name}
  const bySlugName = Object.fromEntries(Object.entries(names).map(([s, n]) => [fold(n), s]));
  const chips = form.querySelector("[data-cl-chips]"), add = form.querySelector(".chip-add");
  const go = form.querySelector("[data-cl-go]"), https = form.querySelector("[data-cl-https]");
  const KEY = "cisteni-ulice";
  let picked = [];
  try { picked = JSON.parse(localStorage.getItem(KEY) || "[]").filter((s) => s in names); } catch (e) { picked = []; }
  const checked = new Set(picked);

  function fold(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim(); }
  function plural(n, one, few, many) { return n === 1 ? one : n >= 2 && n <= 4 ? few : many; }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(picked.filter((s) => checked.has(s)))); } catch (e) { /* private window */ } }
  function url(scheme) {
    return scheme + "://" + location.host + "/verejny-prostor/blokove-cisteni/kalendar.ics?ulice=" + picked.filter((s) => checked.has(s)).join(",");
  }
  function render() {
    chips.textContent = "";
    picked.forEach((s) => {
      const label = document.createElement("label"), box = document.createElement("input");
      label.className = "chip";
      box.type = "checkbox"; box.name = "ulice"; box.value = s; box.checked = checked.has(s);
      box.addEventListener("change", () => { box.checked ? checked.add(s) : checked.delete(s); save(); update(); });
      label.append(box, " " + names[s]);
      chips.append(label);
    });
    update();
  }
  function update() {
    const n = picked.filter((s) => checked.has(s)).length;
    go.textContent = n ? `Přidat ${n} ${plural(n, "ulici", "ulice", "ulic")} do kalendáře` : "Vyberte ulice";
    go.setAttribute("aria-disabled", n ? "false" : "true");
    https.hidden = !n;
    if (n) https.href = url(location.protocol.replace(":", ""));
  }
  function addName() {
    const s = bySlugName[fold(add.value)];
    if (!s) return false;
    if (!picked.includes(s)) picked.push(s);
    checked.add(s);
    add.value = "";
    save();
    render();
    return true;
  }
  add.addEventListener("change", addName);
  add.addEventListener("keydown", (e) => { if (e.key === "Enter" && addName()) e.preventDefault(); });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    addName();
    if (picked.some((s) => checked.has(s))) location.href = url("webcal");
  });
  render();
})();
