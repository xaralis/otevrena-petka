// Uzavírky: the map beside its list (petkamap.js), like the cleaning page.
// <div data-uz-map data-inline="id"> draws the closures of the JSON (each feature's color, width
// and dash: closed red, restricted ink, to come grey, placed approximately dashed; a point a ring).
// Pointing at a stretch or at its row ([data-uz-key]) inks both; a click on the map pins it and
// lights its row; a click on a row moves the map to its stretch (its link goes to the closure's
// text below when the closure is not on the map, or with a modifier key).
(function () {
  const P = window.petkaMap;
  if (!P || !P.ok()) return;
  document.querySelectorAll("[data-uz-map]").forEach((el) => {
    const fc = JSON.parse(document.getElementById(el.dataset.inline).textContent);
    const placed = fc.features.filter((f) => f.geometry);
    const lines = { type: "FeatureCollection", features: placed.filter((f) => !/Point/.test(f.geometry.type)) };
    const points = { type: "FeatureCollection", features: placed.filter((f) => /Point/.test(f.geometry.type)) };
    P.create(el, { cooperative: true }).then((map) => {
      const cl = P.cleaning(map, { id: "uz", data: lines, scheme: "props", by: "key", hit: 16 });
      map.addSource("uz-pt", { type: "geojson", data: points, promoteId: "key" });
      map.addLayer({ id: "uz-pt", source: "uz-pt", type: "circle", paint: {
        "circle-radius": ["case", ["boolean", ["feature-state", "on"], false], 9, 7],
        "circle-color": "#ffffff", "circle-stroke-width": 3,
        "circle-stroke-color": ["case", ["boolean", ["feature-state", "on"], false], P.INK, ["get", "color"]] } });
      if (placed.length) P.fit(map, placed, { padding: 60, maxZoom: 16 });

      const rows = {};
      document.querySelectorAll("[data-uz-key]").forEach((r) => (rows[r.dataset.uzKey] = r));
      let onPt = null;
      const link = P.linker((k) => {
        cl.lit(k ? [k] : []);
        if (onPt) map.setFeatureState({ source: "uz-pt", id: onPt }, { on: false });
        onPt = k && points.features.some((f) => f.properties.key === k) ? k : null;
        if (onPt) map.setFeatureState({ source: "uz-pt", id: onPt }, { on: true });
        Object.entries(rows).forEach(([key, r]) => r.classList.toggle("on", key === k));
      }, { within: () => [el, ...Object.values(rows)] });

      const at = (p) => {
        const f = map.queryRenderedFeatures(p, { layers: [cl.hit, "uz-pt"].filter(Boolean) })[0];
        return f ? f.properties.key : null;
      };
      map.on("mousemove", (e) => { const k = at(e.point); map.getCanvas().style.cursor = k ? "pointer" : ""; if (k) link.hover(k); else link.leave(); });
      map.on("mouseout", () => { map.getCanvas().style.cursor = ""; link.leave(); });
      map.on("click", (e) => {
        const k = at(e.point);
        if (!k) return link.close();
        link.pin(k, true);
        const r = rows[k];
        if (r && link.pinned) r.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
      Object.entries(rows).forEach(([k, r]) => {
        link.wire(r, () => k, { within: true });
        const feats = placed.filter((f) => f.properties.key === k);
        if (!feats.length) return;
        r.querySelector("a").addEventListener("click", (e) => {
          if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
          e.preventDefault();
          P.fit(map, feats, { duration: 500, maxZoom: 17, padding: 70 });
          if (P.narrow()) el.scrollIntoView({ behavior: "smooth", block: "center" });
          map.once("moveend", () => link.pin(k));
        });
      });
    });
  });
})();
