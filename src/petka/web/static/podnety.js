// Podněty: the tiles open one shared detail panel in place (without JS each tile is a link to
// ?detail=…, which the server renders open), the phone's "Všech N druhů", and the grid map
// (self-hosted MapLibre + PMTiles, like cisteni.js): one white circle per ~150 m cell, its area
// by the number of reports, a red-hatched inner circle for those still waiting.
(function () {
  const INK = "#191c1f", RED = "#de091c", PINK = "#f4a3aa";
  const HATCH = 128;     // px of the hatched disc image, added at pixelRatio 2

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

  // --- the map --------------------------------------------------------------------------------
  const el = document.querySelector("[data-pd-map]");
  if (!el || !window.maplibregl || !window.pmtiles) return;
  const grid = JSON.parse(document.getElementById("pd-grid").textContent);
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  const abs = (u) => location.origin + u;
  fetch(el.dataset.style).then((r) => r.json()).then((s) => {
    s.sprite = abs(s.sprite);
    s.glyphs = abs(s.glyphs);
    s.sources.protomaps.url = "pmtiles://" + abs(el.dataset.tiles);
    const map = new maplibregl.Map({
      container: el, style: s, bounds: grid.bounds || undefined, fitBoundsOptions: { padding: 30 },
      minZoom: 11, maxZoom: 18, attributionControl: { compact: true }, cooperativeGestures: true,
      locale: {
        "CooperativeGesturesHandler.WindowsHelpText": "Mapu přiblížíte s klávesou Ctrl a kolečkem myši",
        "CooperativeGesturesHandler.MacHelpText": "Mapu přiblížíte s klávesou ⌘ a kolečkem myši",
        "CooperativeGesturesHandler.MobileHelpText": "Mapou posunete dvěma prsty",
        "NavigationControl.ZoomIn": "Přiblížit", "NavigationControl.ZoomOut": "Oddálit",
      },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      map.addImage("pd-hatch", hatch(), { pixelRatio: 2 });
      map.addSource("pd", { type: "geojson", data: grid });
      // radius in pixels grows with the zoom; area ~ count
      const r = ["interpolate", ["linear"], ["zoom"], ...[[12, 3], [15, 6], [17, 10]].flatMap(([z, k]) =>
        [z, ["max", 3, ["*", k, ["sqrt", ["get", "n"]]]]])];
      map.addLayer({ id: "pd-all", type: "circle", source: "pd",
                     paint: { "circle-radius": r, "circle-color": "#fff", "circle-opacity": .92,
                              "circle-stroke-color": INK, "circle-stroke-width": 1.6 } });
      // the hatched disc is HATCH px wide at pixelRatio 2: icon-size = 2r / HATCH * 2
      const size = ["interpolate", ["linear"], ["zoom"],
        12, ["/", ["*", 2 * 3, ["sqrt", ["get", "waiting"]]], HATCH / 2],
        15, ["/", ["*", 2 * 6, ["sqrt", ["get", "waiting"]]], HATCH / 2],
        17, ["/", ["*", 2 * 10, ["sqrt", ["get", "waiting"]]], HATCH / 2]];
      map.addLayer({ id: "pd-wait", type: "symbol", source: "pd", filter: [">", ["get", "waiting"], 0],
                     layout: { "icon-image": "pd-hatch", "icon-size": size, "icon-allow-overlap": true,
                               "icon-ignore-placement": true } });
      popups(map);
    });
  });

  function hatch() {
    const c = document.createElement("canvas");
    c.width = c.height = HATCH;
    const g = c.getContext("2d");
    g.beginPath(); g.arc(HATCH / 2, HATCH / 2, HATCH / 2, 0, 2 * Math.PI); g.clip();
    g.fillStyle = PINK; g.fillRect(0, 0, HATCH, HATCH);
    g.strokeStyle = RED; g.lineWidth = 6;
    for (let x = -HATCH; x < 2 * HATCH; x += 12) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x + HATCH, HATCH); g.stroke(); }
    return g.getImageData(0, 0, HATCH, HATCH);
  }

  function plural(n, one, few, many) { return n === 1 ? one : n >= 2 && n <= 4 ? few : many; }

  function popups(map) {
    const popup = new maplibregl.Popup({ closeButton: true, maxWidth: "300px", focusAfterOpen: false });
    map.on("mouseenter", "pd-all", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "pd-all", () => (map.getCanvas().style.cursor = ""));
    map.on("click", "pd-all", (e) => {
      const f = e.features[0].properties;
      const cats = typeof f.cats === "string" ? JSON.parse(f.cats) : f.cats;
      const box = document.createElement("div");
      box.className = "map-pop";
      const head = document.createElement("p");
      head.className = "map-pop-h";
      head.textContent = `${f.n} ${plural(f.n, "podnět", "podněty", "podnětů")}`;
      box.append(head);
      if (f.waiting) {
        const w = document.createElement("p");
        w.className = "pd-pop-w";
        w.textContent = `z toho ${f.waiting} ${f.waiting >= 2 && f.waiting <= 4 ? "čekají" : "čeká"}`;
        box.append(w);
      }
      cats.forEach(([name, n]) => {
        const p = document.createElement("p");
        p.textContent = `${name}: ${n}`;
        box.append(p);
      });
      popup.setLngLat(e.features[0].geometry.coordinates).setDOMContent(box).addTo(map);
    });
  }
})();
