// Odpady: the map beside its list (petkamap.js). Kontejner stanoviště ink squares (dashed when
// placed only approximately), sběrné dvory white squares; pointing at a marker or its row lights
// both, a click on a row moves the map to its place, a yard's marker leads to its row below.
(function () {
  const P = window.petkaMap;
  if (!P || !P.ok()) return;
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
      const e = document.createElement(yard ? "a" : "span");
      e.className = "od-mk " + (yard ? "od-mk-d" : "od-mk-v") + (p.approx ? " od-mk-a" : "");
      e.innerHTML = yard ? YARD : CONT;
      if (yard) e.href = "#" + p.key; else e.tabIndex = 0;
      e.title = p.place + (p.when ? ", " + p.when : "");
      e.setAttribute("aria-label", e.title);
      new maplibregl.Marker({ element: e }).setLngLat(f.geometry.coordinates).addTo(map);
      marks[p.key] = e;
    });
    const placed = fc.features.filter((f) => f.properties.kind === "kontejner");
    P.fit(map, placed.length ? placed : fc.features, { padding: 50, maxZoom: 14 });
    const link = P.linker((k) => {
      Object.entries(marks).forEach(([key, m]) => m.classList.toggle("on", key === k));
      Object.entries(rows).forEach(([key, r]) => r.classList.toggle("on", key === k));
    }, { within: () => [el, ...Object.values(rows)] });
    Object.entries(marks).forEach(([k, m]) => link.wire(m, () => k, { pins: !m.href }));
    Object.entries(rows).forEach(([k, r]) => {
      link.wire(r, () => k, { within: true });
      const f = fc.features.find((x) => x.properties.key === k);
      if (!f) return;
      r.querySelector("a").addEventListener("click", (e) => {
        e.preventDefault();
        map.easeTo({ center: f.geometry.coordinates, zoom: Math.max(map.getZoom(), 15), duration: 500 });
        if (P.narrow()) el.scrollIntoView({ behavior: "smooth", block: "center" });
        link.pin(k);
      });
    });
  });
})();
