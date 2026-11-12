// Čištění ulic: the maps (self-hosted MapLibre + PMTiles, like map.js) and the calendar picker.
// <div data-cl-map="all" data-src="/api/v1/cisteni" data-today="YYYY-MM-DD"> colours the obvod's
// places by their next cleaning; <div data-cl-map="street" data-inline="id"> draws one street.
// The picker remembers its streets in localStorage; without JS the form goes to /cisteni/kalendar.
(function () {
  const RED = "#de091c", INK = "#191c1f", GREY = "#8a9097", OFF = "#d6dbe0";

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
        fc.features = fc.features.filter((f) => f.geometry);
        if (all) colour(fc, el.dataset.today); else street(fc);
        map.addSource("cl", { type: "geojson", data: fc });
        const poly = ["==", ["geometry-type"], "Polygon"], line = ["==", ["geometry-type"], "LineString"];
        const solid = ["==", ["get", "dash"], false], dashed = ["==", ["get", "dash"], true];
        map.addLayer({ id: "cl-fill", type: "fill", source: "cl", filter: poly,
                       paint: { "fill-color": ["get", "color"], "fill-opacity": 0.28 } });
        map.addLayer({ id: "cl-edge", type: "line", source: "cl", filter: ["all", poly, solid],
                       paint: { "line-color": ["get", "color"], "line-width": 1.5 } });
        map.addLayer({ id: "cl-edge-d", type: "line", source: "cl", filter: ["all", poly, dashed],
                       paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-dasharray": [2, 2] } });
        map.addLayer({ id: "cl-line", type: "line", source: "cl", filter: ["all", line, solid],
                       layout: { "line-cap": "round", "line-join": "round" },
                       paint: { "line-color": ["get", "color"], "line-width": ["get", "width"] } });
        map.addLayer({ id: "cl-line-d", type: "line", source: "cl", filter: ["all", line, dashed],
                       layout: { "line-join": "round" },
                       paint: { "line-color": ["get", "color"], "line-width": ["get", "width"], "line-dasharray": [1.5, 1.2] } });
        const b = new maplibregl.LngLatBounds();
        const walk = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(walk));
        // the overview fits what is still to be cleaned this year (a long street with nothing
        // left would zoom the map out to the fields); fall back to everything
        const upcoming = all ? fc.features.filter((f) => f.properties.rank > 0) : [];
        (upcoming.length ? upcoming : fc.features).forEach((f) => walk(f.geometry.coordinates));
        if (!b.isEmpty()) map.fitBounds(b, { padding: all ? 20 : 40, maxZoom: 17, duration: 0 });
        if (all) popups(map, el);
      });
    });
  }

  // nearest date: ≤ 7 days red, ≤ 14 ink, later this year grey, none left pale; approximate dashed
  function colour(fc, today) {
    const t0 = Date.parse(today);
    fc.features.forEach((f) => {
      const p = f.properties, days = p.next ? (Date.parse(p.next) - t0) / 864e5 : null;
      const [color, width, rank] = days === null ? [OFF, 2, 0] : days <= 7 ? [RED, 5, 3] : days <= 14 ? [INK, 4, 2] : [GREY, 3, 1];
      Object.assign(p, { color, width, rank, dash: p.status === "approx" || p.status === "partial" });
    });
    fc.features.sort((a, b) => a.properties.rank - b.properties.rank);   // the nearest drawn on top
  }

  // one street: the next cleaning ink, later ones ink dashed, past ones grey
  function street(fc) {
    const look = { next: [INK, 5, false], later: [INK, 3, true], past: [GREY, 4, false] };
    fc.features.forEach((f) => {
      const [color, width, dash] = look[f.properties.when];
      Object.assign(f.properties, { color, width, dash });
    });
  }

  function popups(map, el) {
    const layers = ["cl-fill", "cl-line", "cl-line-d"];
    const popup = new maplibregl.Popup({ closeButton: true, maxWidth: "320px", focusAfterOpen: false });
    layers.forEach((id) => {
      map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
    });
    const dm = (iso) => { const [, m, d] = iso.split("-").map(Number); return `${d}. ${m}.`; };
    map.on("click", (e) => {
      const p = e.point, pad = 5;
      const hits = map.queryRenderedFeatures([[p.x - pad, p.y - pad], [p.x + pad, p.y + pad]], { layers });
      if (!hits.length) return;
      const seen = new Set(), box = document.createElement("div");
      box.className = "map-pop";
      hits.forEach((h) => {
        const f = h.properties;
        if (seen.has(f.key)) return;
        seen.add(f.key);
        const texts = typeof f.texts === "string" ? JSON.parse(f.texts) : f.texts;
        const dates = typeof f.dates === "string" ? JSON.parse(f.dates) : f.dates;
        const head = document.createElement("p");
        head.className = "map-pop-h";
        if (f.slug) {
          const a = document.createElement("a");
          a.href = "/cisteni/ulice/" + f.slug;
          a.textContent = f.street;
          head.append(a);
        } else head.textContent = texts[0];
        const t = document.createElement("p");
        t.textContent = texts[0];
        const d = document.createElement("p");
        d.className = "cl-pop-d";
        d.textContent = dates.map((x) => dm(x.date) + (x.time ? (x.before ? " před " : " od ") + x.time.replace(/^0/, "") : "")).join(", ");
        box.append(head, t, d);
      });
      popup.setLngLat(e.lngLat).setDOMContent(box).addTo(map);
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
    return scheme + "://" + location.host + "/cisteni/kalendar.ics?ulice=" + picked.filter((s) => checked.has(s)).join(",");
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
