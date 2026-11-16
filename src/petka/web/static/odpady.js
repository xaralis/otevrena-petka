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
