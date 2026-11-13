// The front page's „Aktuálně“ (self-hosted MapLibre + PMTiles, like ulice.js): one map with
//   lines    this week's blokové čištění, grey; the street pointed at (or its day in the box) black
//   anchors  one per cleaned street, where its tooltip hangs (focusable, zero size)
//   marks    úřední deska notices that name a street: hatched = a traffic measure, white with the
//            kind's icon = anything else; DOM markers, so they take focus and show a tooltip
// Rows of the two boxes point at their features. Pointing shows, a click or a tap pins (phones
// have no hover); a click elsewhere on the map unpins. Data: <script id=…> from ulice/web.py.
(function () {
  const el = document.querySelector("[data-ak-map]");
  if (!el || !window.maplibregl || !window.pmtiles || !window.mapTip) return;
  const GREY = "#7d838b", INK = "#191c1f";
  const data = JSON.parse(document.getElementById(el.dataset.inline).textContent);
  const stage = el.closest(".ak");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const narrow = () => window.matchMedia("(max-width: 900px)").matches;
  const abs = (u) => location.origin + u;

  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
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
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.on("load", () => draw(map));
  });

  const tip = window.mapTip.make;

  function draw(map) {
    const w = (extra) => ["interpolate", ["linear"], ["zoom"], 12, 4 + extra, 15, 6 + extra, 18, 9 + extra];
    map.addSource("ak-cl", { type: "geojson", data: data.lines });
    const line = { type: "line", source: "ak-cl", layout: { "line-cap": "round", "line-join": "round" } };
    const fade = reduce ? {} : { "line-opacity": 0, "line-opacity-transition": { duration: 500, delay: 0 } };
    map.addLayer({ ...line, id: "ak-cl-case", paint: { "line-color": "#ffffff", "line-width": w(4), ...fade } });
    map.addLayer({ ...line, id: "ak-cl", paint: { "line-color": GREY, "line-width": w(0), ...fade } });
    map.addLayer({ ...line, id: "ak-cl-on", filter: ["in", ["get", "key"], ["literal", []]],
                   paint: { "line-color": INK, "line-width": w(0) } });
    map.addLayer({ ...line, id: "ak-cl-hit", paint: { "line-color": INK, "line-opacity": 0, "line-width": 22 } });
    const labels = map.getStyle().layers.find((l) => l.type === "symbol" && !l.id.startsWith("ak-"));
    if (labels) ["ak-cl-case", "ak-cl", "ak-cl-on"].forEach((id) => map.moveLayer(id, labels.id));
    if (!reduce) setTimeout(() => ["ak-cl-case", "ak-cl"].forEach((id) => map.setPaintProperty(id, "line-opacity", 1)), 400);

    // what each street, day and mark lights up
    const keysOf = {};
    data.lines.features.forEach((f) => (keysOf[f.properties.sid] ||= []).push(f.properties.key));
    const anchor = {}, mark = {};
    data.anchors.forEach((a) => {
      const e = document.createElement("a");     // the street's cleaning page
      e.href = a.href;
      e.className = "ak-cla";
      e.tabIndex = 0;
      e.setAttribute("aria-label", a.label);
      e.appendChild(tip(a.street, "Blokové čištění", a.when));
      anchor[a.sid] = e;
      new maplibregl.Marker({ element: e }).setLngLat([a.lng, a.lat]).addTo(map);
    });
    data.marks.forEach((m, i) => {
      const e = document.createElement(m.nid ? "a" : "span");    // the marker opens its notice
      if (m.nid) e.href = "/uredni-deska/" + encodeURIComponent(m.nid);
      e.className = "ak-mk" + (m.traffic ? " ak-mk-t" : "");
      e.tabIndex = 0;
      e.setAttribute("aria-label", m.label);
      if (!reduce) e.style.animationDelay = (0.25 + 0.06 * i).toFixed(2) + "s";
      const box = document.createElement("i");
      if (!m.traffic) {
        const NS = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(NS, "svg"), use = document.createElementNS(NS, "use");
        svg.setAttribute("width", "19"); svg.setAttribute("height", "19"); svg.setAttribute("aria-hidden", "true");
        use.setAttribute("href", el.dataset.icons + "#" + m.kind);
        svg.appendChild(use);
        box.appendChild(svg);
      }
      e.append(box, tip(m.street, m.what, m.when));
      mark[m.id] = e;
      new maplibregl.Marker({ element: e }).setLngLat([m.lng, m.lat]).addTo(map);
    });
    const street = (sid) => ({ els: [anchor[sid]].filter(Boolean), keys: keysOf[sid] || [] });
    const day = (i, row) => {
      const d = data.days[i];
      return { els: [row, ...d.sids.map((s) => anchor[s]).filter(Boolean)], keys: d.keys };
    };
    const one = (id, row) => ({ els: [row, mark[id]].filter(Boolean), keys: [] });

    let pinned = null;
    function apply(st) {
      stage.querySelectorAll(".on").forEach((e) => e.classList.remove("on", "ak-l"));
      map.setFilter("ak-cl-on", ["in", ["get", "key"], ["literal", st ? st.keys : []]]);
      if (!st) return;
      const edge = el.getBoundingClientRect().right, rbox = stage.querySelector(".ak-box-r");
      const r = rbox && !narrow() ? rbox.getBoundingClientRect() : null;
      st.els.forEach((e) => {
        e.classList.add("on");
        // the tooltip goes to the left where it would run off the map or over the right box
        if (e.matches(".ak-mk, .ak-cla")) window.mapTip.side(e, edge, r);
      });
    }
    const hover = (st) => apply(st || pinned);
    const pin = (st, same) => { pinned = same ? null : st; apply(pinned); };
    const sameAs = (st) => pinned && st.els.length && pinned.els[0] === st.els[0] && pinned.keys.join() === st.keys.join();

    map.on("mousemove", "ak-cl-hit", (e) => { map.getCanvas().style.cursor = "pointer"; hover(street(e.features[0].properties.sid)); });
    map.on("mouseleave", "ak-cl-hit", () => { map.getCanvas().style.cursor = ""; hover(null); });
    map.on("click", (e) => {
      if (e.originalEvent.target.closest && e.originalEvent.target.closest(".ak-mk, .ak-cla")) return;
      const f = map.queryRenderedFeatures(e.point, { layers: ["ak-cl-hit"] })[0];
      const st = f ? street(f.properties.sid) : null;
      // a stretch opens its street's cleaning page like a marker opens its notice: at once on
      // wide screens, on phones with a second tap
      const a = f && anchor[f.properties.sid];
      if (a && a.href && (!narrow() || sameAs(st))) { window.location.href = a.href; return; }
      pin(st, st && sameAs(st));
    });
    const wire = (e, make) => {
      e.addEventListener("mouseenter", () => hover(make()));
      e.addEventListener("mouseleave", () => hover(null));
      e.addEventListener("focus", () => hover(make()));
      e.addEventListener("blur", () => hover(null));
      e.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const st = make();
        // a marker is a link: on wide screens it opens the notice straight away, on phones the
        // first tap shows the tooltip and a second tap on the same marker opens it
        if (e.href && (!narrow() || sameAs(st))) return;
        ev.preventDefault();
        pin(st, sameAs(st));
      });
    };
    Object.entries(mark).forEach(([id, e]) => wire(e, () => one(id)));
    Object.entries(anchor).forEach(([sid, e]) => wire(e, () => street(sid)));
    stage.querySelectorAll("[data-day]").forEach((r) => wire(r, () => day(+r.dataset.day, r)));
    stage.querySelectorAll("[data-mark]").forEach((r) => wire(r, () => one(r.dataset.mark, r)));

    // everything in view, clear of the boxes on wide screens
    const b = new maplibregl.LngLatBounds();
    const walk = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(walk));
    data.lines.features.forEach((f) => walk(f.geometry.coordinates));
    data.marks.forEach((m) => b.extend([m.lng, m.lat]));
    if (b.isEmpty()) return;
    const side = (cls) => { const x = stage.querySelector(cls); return x ? x.offsetWidth + 40 : 40; };
    const pad = narrow() ? 28 : { top: 40, bottom: 40, left: side(".ak-box-l"), right: side(".ak-box-r") };
    map.fitBounds(b, { padding: pad, maxZoom: 15.5, duration: 0 });
  }
})();
