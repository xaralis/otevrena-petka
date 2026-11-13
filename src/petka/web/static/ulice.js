// The street pages' map (self-hosted MapLibre + PMTiles, like cisteni.js and podnety.js) and the
// short placeholder of the street search on phones (the front page's map is aktualne.js).
//   <div data-ul-map="street" data-inline="id"> the street from RÚIAN, its cleanings (the next ink,
//        later dashed, past grey) and its reports by cell (white disc, hatched part waiting)
(function () {
  const RED = "#de091c", INK = "#191c1f", GREY = "#8a9097", PINK = "#f4a3aa";
  const HATCH = 128;     // px of the hatched disc image, added at pixelRatio 2

  if (window.matchMedia("(max-width: 600px)").matches)
    document.querySelectorAll("input[data-short]").forEach((i) => (i.placeholder = i.dataset.short));

  const maps = document.querySelectorAll("[data-ul-map]");
  if (!maps.length || !window.maplibregl || !window.pmtiles) return;
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  maps.forEach(setup);

  function setup(el) {
    const fc = JSON.parse(document.getElementById(el.dataset.inline).textContent);
    const abs = (u) => location.origin + u;
    fetch(el.dataset.style).then((r) => r.json()).then((s) => {
      s.sprite = abs(s.sprite);
      s.glyphs = abs(s.glyphs);
      s.sources.protomaps.url = "pmtiles://" + abs(el.dataset.tiles);
      const map = new maplibregl.Map({
        container: el, style: s,
        bounds: [[15.738, 49.996], [15.812, 50.043]], maxBounds: [[15.64, 49.95], [15.90, 50.09]],
        minZoom: 11, maxZoom: 18.5, attributionControl: { compact: true }, cooperativeGestures: true,
        locale: {
          "CooperativeGesturesHandler.WindowsHelpText": "Mapu přiblížíte s klávesou Ctrl a kolečkem myši",
          "CooperativeGesturesHandler.MacHelpText": "Mapu přiblížíte s klávesou ⌘ a kolečkem myši",
          "CooperativeGesturesHandler.MobileHelpText": "Mapou posunete dvěma prsty",
          "NavigationControl.ZoomIn": "Přiblížit", "NavigationControl.ZoomOut": "Oddálit",
        },
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      map.on("load", () => draw(map, fc));
    });
  }

  function draw(map, fc) {
    const look = { next: [INK, 5, false], later: [INK, 3, true], past: [GREY, 4, false] };
    fc.features.forEach((f) => {
      const p = f.properties;
      if (p.kind === "cleaning") [p.color, p.width, p.dash] = look[p.when];
    });
    map.addImage("ul-hatch", hatch(), { pixelRatio: 2 });
    map.addSource("ul", { type: "geojson", data: fc });
    const is = (k) => ["==", ["get", "kind"], k];
    const w = (extra) => ["interpolate", ["linear"], ["zoom"],
      ...[[12, 0.75], [15, 1], [18, 1.8]].flatMap(([z, k]) => [z, ["*", ["+", ["get", "width"], extra], k]])];
    map.addLayer({ id: "ul-street", type: "line", source: "ul", filter: is("street"),
                   layout: { "line-cap": "round", "line-join": "round" },
                   paint: { "line-color": INK, "line-opacity": 0.14, "line-width": ["interpolate", ["linear"], ["zoom"], 13, 8, 18, 22] } });
    map.addLayer({ id: "ul-case", type: "line", source: "ul", filter: is("cleaning"),
                   layout: { "line-cap": "round", "line-join": "round" },
                   paint: { "line-color": "#ffffff", "line-width": w(3) } });
    map.addLayer({ id: "ul-line", type: "line", source: "ul", filter: ["all", is("cleaning"), ["==", ["get", "dash"], false]],
                   layout: { "line-cap": "round", "line-join": "round" },
                   paint: { "line-color": ["get", "color"], "line-width": w(0) } });
    map.addLayer({ id: "ul-line-d", type: "line", source: "ul", filter: ["all", is("cleaning"), ["==", ["get", "dash"], true]],
                   layout: { "line-join": "round" },
                   paint: { "line-color": ["get", "color"], "line-width": w(0), "line-dasharray": [1.5, 1.2] } });
    // reports by cell: radius ~ sqrt(count), like /podnety
    const r = ["interpolate", ["linear"], ["zoom"], ...[[12, 3], [15, 6], [17, 10]].flatMap(([z, k]) =>
      [z, ["max", 3, ["*", k, ["sqrt", ["get", "n"]]]]])];
    map.addLayer({ id: "ul-rep", type: "circle", source: "ul", filter: is("reports"),
                               paint: { "circle-radius": r, "circle-color": "#fff", "circle-opacity": .92,
                                        "circle-stroke-color": INK, "circle-stroke-width": 1.6 } });
    const size = ["interpolate", ["linear"], ["zoom"], ...[[12, 3], [15, 6], [17, 10]].flatMap(([z, k]) =>
      [z, ["/", ["*", 2 * k, ["sqrt", ["max", 1, ["get", "waiting"]]]], HATCH / 2]])];
    map.addLayer({ id: "ul-wait", type: "symbol", source: "ul", filter: ["all", is("reports"), [">", ["get", "waiting"], 0]],
                   layout: { "icon-image": "ul-hatch", "icon-size": size, "icon-allow-overlap": true, "icon-ignore-placement": true } });
    const labels = map.getStyle().layers.find((l) => l.type === "symbol" && !l.id.startsWith("ul-"));
    if (labels) ["ul-street", "ul-case", "ul-line", "ul-line-d"].forEach((id) => map.moveLayer(id, labels.id));

    const b = new maplibregl.LngLatBounds();
    const walk = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(walk));
    fc.features.filter((f) => f.properties.kind !== "reports").forEach((f) => walk(f.geometry.coordinates));
    if (!b.isEmpty()) map.fitBounds(b, { padding: 40, maxZoom: 17, duration: 0 });
  }

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
})();
