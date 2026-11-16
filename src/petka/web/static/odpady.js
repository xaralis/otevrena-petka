// Odpady: the map beside its list (petkamap.js). Kontejner stanoviště ink squares (grey, dashed
// when placed only approximately), sběrné dvory white squares; each with its card in the map (the
// portal's .ak-tip: the next dates, or whether the yard is open and its hours). Pointing at a
// marker or its row shows the card and lights both, a click or a tap pins it (a click elsewhere
// unpins); a click on a row moves the map to its place and pins it.
(function () {
  const P = window.petkaMap;
  if (!P || !P.ok() || !window.mapTip) return;
  const el = document.querySelector("[data-od-map]");
  if (!el) return;
  const fc = JSON.parse(document.getElementById(el.dataset.inline).textContent);
  const CONT = '<svg width="13" height="11" viewBox="0 0 14 12" aria-hidden="true"><path d="M1 3h12l-1.6 8H2.6z" fill="#fff"/><rect y="1" width="14" height="2" fill="#fff"/></svg>';
  const YARD = '<svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 6.5 7 2.5l5 4V12H2z" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
  P.create(el, { cooperative: true }).then((map) => {
    const rows = {};
    document.querySelectorAll("[data-od-key]").forEach((r) => (rows[r.dataset.odKey] = r));
    const marks = {};
    fc.features.forEach((f) => {
      const p = f.properties, yard = p.kind === "dvur";
      const e = document.createElement("span");
      e.className = "ak-mk od-at";
      e.tabIndex = 0;
      e.setAttribute("aria-label", [p.place, p.what, p.when].filter(Boolean).join(", "));
      const box = document.createElement("i");
      box.className = "od-mk " + (yard ? "od-mk-d" : "od-mk-v") + (p.approx ? " od-mk-a" : "");
      box.innerHTML = yard ? YARD : CONT;
      e.append(box, window.mapTip.make(p.place, p.what, p.when));
      new maplibregl.Marker({ element: e }).setLngLat(f.geometry.coordinates).addTo(map);
      marks[p.key] = e;
    });
    const placed = fc.features.filter((f) => f.properties.kind === "kontejner");
    P.fit(map, placed.length ? placed : fc.features, { padding: 50, maxZoom: 14 });

    const link = P.linker((k) => {
      el.querySelectorAll(".ak-mk.on").forEach((m) => m.classList.remove("on", "ak-l"));
      Object.entries(rows).forEach(([key, r]) => r.classList.toggle("on", key === k));
      if (k && marks[k]) P.light([marks[k]], el.getBoundingClientRect().right);
    }, { within: () => [el, ...Object.values(rows)] });
    Object.entries(marks).forEach(([k, m]) => link.wire(m, () => k, { pins: true }));
    map.on("click", (e) => { if (!(e.originalEvent.target.closest && e.originalEvent.target.closest(".ak-mk"))) link.close(); });
    Object.entries(rows).forEach(([k, r]) => {
      link.wire(r, () => k, { within: true });
      const f = fc.features.find((x) => x.properties.key === k);
      if (!f) return;
      r.querySelector("a").addEventListener("click", (e) => {
        e.preventDefault();
        map.easeTo({ center: f.geometry.coordinates, zoom: Math.max(map.getZoom(), 15), duration: 500 });
        if (P.narrow()) el.scrollIntoView({ behavior: "smooth", block: "center" });
        map.once("moveend", () => link.pin(k));
      });
    });
  });
})();

// Kontejnery na tříděný odpad: a dot per stanoviště, in its kind's colour when a kind is chosen
// (the switch above the map, no reload), white with an ink ring when it takes several; a click
// shows its card (address, what it takes) in the map.
(function () {
  const P = window.petkaMap;
  const el = document.querySelector("[data-od-bins]");
  if (!el || !P || !P.ok() || !window.mapTip) return;
  const fc = JSON.parse(document.getElementById(el.dataset.inline).textContent);
  const sorts = JSON.parse(document.getElementById("od-sorts").textContent);
  const colour = Object.fromEntries(sorts.map((s) => [s.key, s.color]));
  const nav = document.querySelector("[data-od-sorts]");
  P.create(el, { cooperative: true }).then((map) => {
    fc.features.forEach((f) => { const o = f.properties.odpad; f.properties.c = o.length === 1 ? colour[o[0]] || "#191c1f" : "#ffffff"; });
    map.addSource("od-b", { type: "geojson", data: fc });
    map.addLayer({ id: "od-b", source: "od-b", type: "circle", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 3.5, 15, 6, 17, 8],
      "circle-color": ["get", "c"], "circle-stroke-color": "#191c1f",
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 12, 1, 15, 1.6] } });
    P.fit(map, fc.features, { padding: 30, maxZoom: 15 });
    // the card: one zero-size marker moved to the stanoviště clicked
    const tip = document.createElement("span");
    tip.className = "ak-mk ak-cla od-tip";
    const marker = new maplibregl.Marker({ element: tip });
    const show = (f) => {
      tip.replaceChildren(window.mapTip.make(f.properties.place, f.properties.what, ""));
      marker.setLngLat(f.geometry.coordinates).addTo(map);
      P.light([tip], el.getBoundingClientRect().right);
    };
    map.on("click", (e) => {
      const f = map.queryRenderedFeatures(e.point, { layers: ["od-b"] })[0];
      if (f) show(f); else marker.remove();
    });
    map.on("mousemove", "od-b", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "od-b", () => (map.getCanvas().style.cursor = ""));
    nav && nav.addEventListener("click", (e) => {
      const a = e.target.closest("[data-sort]");
      if (!a) return;
      e.preventDefault();
      nav.querySelectorAll("a").forEach((x) => (x === a ? x.setAttribute("aria-current", "true") : x.removeAttribute("aria-current")));
      const k = a.dataset.sort;
      marker.remove();
      map.setFilter("od-b", k ? ["in", k, ["get", "odpad"]] : null);
      map.setPaintProperty("od-b", "circle-color", k ? colour[k] : ["get", "c"]);
    });
  });
})();

// Svoz směsného odpadu: the field filters the street list as you type (accents and case ignored).
(function () {
  const q = document.querySelector("[data-od-svoz-q]"), list = document.querySelector("[data-od-svoz]");
  if (!q || !list) return;
  const none = document.querySelector("[data-od-svoz-none]");
  const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  const rows = [...list.children].map((li) => [li, fold(li.dataset.n)]);
  q.addEventListener("input", () => {
    const t = fold(q.value);
    let n = 0;
    rows.forEach(([li, k]) => { const on = !t || k.includes(t); li.hidden = !on; n += on; });
    none.hidden = n > 0;
  });
})();
