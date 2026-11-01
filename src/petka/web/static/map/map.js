// Maps of resolution places: self-hosted MapLibre + PMTiles, nothing loaded from third parties.
// <div data-map="detail" data-inline="places-json"> (one resolution) or
// <div data-map="all" data-src="/api/v1/usneseni/places.geojson?..."> (the map page).
(function () {
  const el = document.querySelector("[data-map]");
  if (!el || !window.maplibregl) return;
  const RED = "#de091c", INK = "#191c1f";
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  const detail = el.dataset.map === "detail";
  // MapLibre wants absolute URLs for sprites, glyphs and the PMTiles archive
  const abs = (u) => location.origin + u;
  const style = fetch(el.dataset.style).then((r) => r.json()).then((s) => {
    s.sprite = abs(s.sprite);
    s.glyphs = abs(s.glyphs);
    s.sources.protomaps.url = "pmtiles://" + abs(el.dataset.tiles);
    return s;
  });
  style.then((s) => init(s));
  function init(styleJson) {
  const map = new maplibregl.Map({
    container: el, style: styleJson,
    bounds: [[15.738, 49.996], [15.812, 50.043]], maxBounds: [[15.64, 49.95], [15.90, 50.09]],  // = the tile extract
    minZoom: 11, maxZoom: 18.5, attributionControl: { compact: true },
    cooperativeGestures: detail, locale: {
      "CooperativeGesturesHandler.WindowsHelpText": "Mapu přiblížíte s klávesou Ctrl a kolečkem myši",
      "CooperativeGesturesHandler.MacHelpText": "Mapu přiblížíte s klávesou ⌘ a kolečkem myši",
      "CooperativeGesturesHandler.MobileHelpText": "Mapou posunete dvěma prsty",
      "NavigationControl.ZoomIn": "Přiblížit", "NavigationControl.ZoomOut": "Oddálit",
    },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  const data = el.dataset.src
    ? fetch(el.dataset.src).then((r) => r.json())
    : Promise.resolve(JSON.parse(document.getElementById(el.dataset.inline).textContent));

  map.on("load", async () => {
    const fc = await data;
    map.addSource("places", { type: "geojson", data: fc });
    const poly = ["==", ["geometry-type"], "Polygon"], line = ["==", ["geometry-type"], "LineString"],
          point = ["==", ["geometry-type"], "Point"];
    map.addLayer({ id: "p-fill", type: "fill", source: "places", filter: poly,
                   paint: { "fill-color": RED, "fill-opacity": detail ? 0.3 : 0.22 } });
    map.addLayer({ id: "p-edge", type: "line", source: "places", filter: poly,
                   paint: { "line-color": RED, "line-width": 1.5 } });
    map.addLayer({ id: "p-line", type: "line", source: "places", filter: line,
                   layout: { "line-cap": "round", "line-join": "round" },
                   paint: { "line-color": RED, "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2.5, 17, 7], "line-opacity": 0.75 } });
    map.addLayer({ id: "p-point", type: "circle", source: "places", filter: point,
                   paint: { "circle-color": RED, "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 4, 17, 8],
                            "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
    const layers = ["p-fill", "p-line", "p-point"];

    if (fc.features.length) {
      const b = new maplibregl.LngLatBounds();
      const walk = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(walk));
      fc.features.forEach((f) => walk(f.geometry.coordinates));
      if (detail) map.fitBounds(b, { padding: 48, maxZoom: 17, duration: 0 });
    }

    const popup = new maplibregl.Popup({ closeButton: true, maxWidth: "320px", focusAfterOpen: false });
    // keep the whole popup inside the map: pan by however much it sticks out
    const fit = () => requestAnimationFrame(() => {
      const box = popup.getElement(), pad = 12;
      if (!box) return;
      const p = box.getBoundingClientRect(), m = el.getBoundingClientRect();
      const dx = p.left < m.left + pad ? p.left - m.left - pad : p.right > m.right - pad ? p.right - m.right + pad : 0;
      const dy = p.top < m.top + pad ? p.top - m.top - pad : p.bottom > m.bottom - pad ? p.bottom - m.bottom + pad : 0;
      if (dx || dy) map.panBy([dx, dy], { duration: 250 });
    });
    layers.forEach((id) => {
      map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
    });
    map.on("click", (e) => {
      const p = e.point, pad = 5;
      const hits = map.queryRenderedFeatures([[p.x - pad, p.y - pad], [p.x + pad, p.y + pad]], { layers });
      if (!hits.length) return;
      const box = document.createElement("div");
      box.className = "map-pop";
      if (detail) {
        const seen = new Set();
        hits.forEach((h) => { if (!seen.has(h.properties.label)) { seen.add(h.properties.label);
          const d = document.createElement("p"); d.textContent = h.properties.label; box.append(d); } });
      } else {
        const byUid = new Map();
        hits.forEach((h) => byUid.has(h.properties.uid) || byUid.set(h.properties.uid, h.properties));
        const items = [...byUid.values()].sort((a, b) => (a.date < b.date ? 1 : -1));
        const head = document.createElement("p");
        head.className = "map-pop-h";
        head.textContent = hits[0].properties.label;
        box.append(head);
        items.slice(0, 8).forEach((r) => {
          const a = document.createElement("a");
          a.href = "/usneseni/" + r.uid;
          const n = document.createElement("b"); n.textContent = r.number + " ";
          a.append(n, document.createTextNode(r.title || ""));
          const d = document.createElement("small");
          d.textContent = " " + r.date.split("-").reverse().map(Number).join(". ");
          const li = document.createElement("p"); li.append(a, d); box.append(li);
        });
        if (items.length > 8) { const m = document.createElement("p"); m.className = "map-pop-more";
          m.textContent = "a dalších " + (items.length - 8) + " – přibližte mapu"; box.append(m); }
      }
      popup.setLngLat(e.lngLat).setDOMContent(box).addTo(map);
      fit();
    });
  });
  }
})();
