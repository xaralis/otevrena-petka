// A street's „Aktuálně“ (the map is petkamap.js) and the short placeholder of the street search
// on phones.
//   street    the base map's road of that name, RÚIAN's line where it has none
//   cleaning  this year's cleaned places on the street: the upcoming ones grey, the one pointed
//             at (or its row) ink with its tooltip; past ones drawn only while their row is
//   reports   points and clusters as on /verejny-prostor/podnety, the card on a report; a click
//             pins it (on phones under the map), Escape or a click elsewhere closes it, a click
//             on a cluster zooms in
//   marks     úřední deska notices naming the street
// The list's rows and the map point at each other: a row lights its features up (a report's
// point or the cluster it is in outlined, a single report's card), a feature its row.
// Data: <script id=ul-map-json> from ulice/web.py street().
(function () {

  // a narrow field takes the short placeholder ("Třeba Wolkerova"), measured, not by the window
  const fit = () => document.querySelectorAll("input[data-short]").forEach((i) => {
    i.dataset.long ||= i.placeholder;
    if (i.offsetWidth) i.placeholder = i.offsetWidth < 380 ? i.dataset.short : i.dataset.long;
  });
  fit();
  window.addEventListener("resize", fit);

  const el = document.querySelector("[data-ul-map]");
  const P = window.petkaMap;
  if (!el || !P || !P.ok() || !window.mapTip) return;
  const data = JSON.parse(document.getElementById(el.dataset.inline).textContent);
  const stage = el.closest(".ul-akt");
  const wrap = el.parentElement;
  const reports = data.reports.features;
  const byId = new Map(reports.map((f) => [f.properties.id, f]));
  const idsOf = {};
  reports.forEach((f) => { if (f.properties.row) (idsOf[f.properties.row] ||= []).push(f.properties.id); });
  const list = document.querySelector("[data-ul-rows]");
  const rowEl = (k) => (list ? list.querySelector(`li[data-row="${k}"]`) : null);
  const ahead = (f) => !f.properties.past;

  // in view from the start: the street (RÚIAN's line, the base map's road once it is loaded) and
  // everything the list shows on the map, so no row points off the map
  const shown = [...reports, ...data.marks];
  P.create(el, { bounds: P.bounds([data.street, ...shown]) || undefined, fitBoundsOptions: { padding: 40, maxZoom: 17 }, font: true }).then((map) => {
    const sl = P.street(map, { id: "ul-street", geometry: data.street, name: el.dataset.name,
                               paint: { "line-color": P.INK, "line-opacity": 0.14, "line-width": ["interpolate", ["linear"], ["zoom"], 13, 8, 18, 22] },
                               refit: (b) => P.fit(map, [...(b ? [b.toArray()] : []), ...data.cleaning.features.filter(ahead), ...shown]) });
    const cl = P.cleaning(map, { id: "ul-cl", data: data.cleaning, scheme: "grey", by: "row", hit: 22, areas: "fill",
                                 show: ["==", ["get", "past"], false] });
    P.belowLabels(map, sl);
    sl.forEach((id) => map.moveLayer(id, cl.layers[0]));      // the street under the cleanings
    const rep = P.reports(map, { id: "ur", data: data.reports, wrap, owners: true });   // the card in the map, as on Podněty
    const anchor = P.anchors(map, data.anchors.map((a) => ({ ...a, what: a.text })), { key: "row", hidden: true });
    const mark = P.marks(map, data.marks.map((m) => ({ ...m, title: m.what, what: "Úřední deska" })), { icons: el.dataset.icons, key: "row" });

    // a state: {keys: [row keys], ids: [report ids outlined], card: a report's id or null}
    // a row lit from the map comes into view in its list, which scrolls on its own beside the map
    // (the page stays put); on a phone the list is not a box of its own
    const reveal = (r) => {
      if (!r || !list || list.scrollHeight <= list.clientHeight) return;
      const lt = list.getBoundingClientRect(), rt = r.getBoundingClientRect();
      if (rt.top < lt.top) list.scrollTop -= lt.top - rt.top;
      else if (rt.bottom > lt.bottom) list.scrollTop += rt.bottom - lt.bottom;
    };
    const fromRow = (k) => { const ids = idsOf[k] || []; return { keys: [k], ids, card: ids.length === 1 ? ids[0] : null }; };
    const fromReport = (id) => ({ keys: [byId.get(id).properties.row].filter(Boolean), ids: [id], card: id });
    const link = P.linker((st) => {
      stage.querySelectorAll(".on").forEach((e) => { if (e !== rep.card.el) e.classList.remove("on", "ak-l"); });
      const keys = st ? st.keys : [];
      cl.lit(keys);
      keys.forEach((k) => { const r = rowEl(k); if (r) r.classList.add("on"); });
      if (keys.length) reveal(rowEl(keys[0]));
      P.light(keys.flatMap((k) => [anchor[k], mark[k]]), el.getBoundingClientRect().right);
      rep.ring((st ? st.ids : []).map((id) => rep.owner(id)));
      if (st && st.card != null) rep.card.show(st.card, { enter: () => link.keep(), leave: () => link.leave() });
      else rep.card.hide();
    }, { delay: 250, within: () => [wrap, list] });
    rep.onCount(link.redraw);

    map.on("mousemove", rep.pt, (e) => { map.getCanvas().style.cursor = "pointer"; link.hover(fromReport(e.features[0].properties.id)); });
    map.on("mouseleave", rep.pt, () => { map.getCanvas().style.cursor = ""; link.leave(); });
    map.on("mousemove", rep.cl, (e) => {
      map.getCanvas().style.cursor = "pointer";
      const ids = rep.leaves(e.features[0].properties.cluster_id);
      link.hover({ keys: [...new Set(ids.map((i) => byId.get(i).properties.row).filter(Boolean))], ids, card: null });
    });
    map.on("mouseleave", rep.cl, () => { map.getCanvas().style.cursor = ""; link.leave(); });
    map.on("mousemove", cl.hit, (e) => {
      if (map.queryRenderedFeatures(e.point, { layers: [rep.pt, rep.cl] }).length) return;
      map.getCanvas().style.cursor = "pointer";
      link.hover({ keys: [e.features[0].properties.row], ids: [], card: null });
    });
    map.on("mouseleave", cl.hit, () => { map.getCanvas().style.cursor = ""; link.leave(); });
    map.on("click", (e) => {
      const f = map.queryRenderedFeatures(e.point, { layers: [rep.pt, rep.cl] })[0];
      if (!f) { link.close(); return; }
      if (f.layer.id === rep.cl) { link.close(); rep.zoomInto(f); return; }
      link.pin(fromReport(f.properties.id));    // the card has a toggle and a link: a click (a tap) pins it
    });
    // pointing at a row shows its place – only where the card floats over the map; under the map
    // (a narrow window) the map is above the list, out of sight, so
    // there a row shows its place on a click (below)
    const floats = window.matchMedia("(min-width: 901px) and (hover: hover)");
    if (list) list.querySelectorAll("li[data-row]").forEach((li) => {
      const a = li.firstElementChild, make = () => fromRow(li.dataset.row);
      a.addEventListener("mouseenter", () => { if (floats.matches) link.hover(make()); });
      a.addEventListener("mouseleave", () => { if (floats.matches) link.leave(); });
      a.addEventListener("focus", () => { if (floats.matches) link.hover(make()); });
      a.addEventListener("blur", () => { if (floats.matches) link.leave(); });
    });
    // the control beside a row, and a click on a row with a place: the map moves to what the row
    // is about and keeps it shown
    const featuresOf = (k) => [
      ...(idsOf[k] || []).map((id) => byId.get(id)),
      ...data.cleaning.features.filter((f) => f.properties.row === k),
      ...data.marks.filter((m) => m.row === k),
      ...data.anchors.filter((a) => a.row === k),
    ];
    const focus = (k) => {
      P.fit(map, featuresOf(k), { duration: 500, maxZoom: 17,
            padding: window.matchMedia("(max-width: 600px)").matches ? { top: 50, left: 40, right: 40, bottom: 200 } : 70 });   // above the card on a phone   // as a row of Blokové čištění
      if (window.matchMedia("(max-width: 900px)").matches) el.scrollIntoView({ behavior: "smooth", block: "center" });
      map.once("moveend", () => link.pin(fromRow(k)));
    };
    if (list) list.querySelectorAll("[data-ul-pin]").forEach((b) => b.addEventListener("click", (e) => {
      e.preventDefault();
      focus(b.dataset.ulPin);
    }));
    // a row with a place on the map: a click shows it there (its card links on, to Dej Tip or the
    // notice); a row without one (a resolution) stays a link
    // the reports panel's waiting rows: down to the map, the report shown there
    document.querySelectorAll("[data-ul-focus]").forEach((a) => a.addEventListener("click", (e) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
      e.preventDefault();
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      focus(a.dataset.ulFocus);
    }));
    if (list) list.querySelectorAll("li.ul-mapped[data-row] > a").forEach((a) => a.addEventListener("click", (e) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;      // a new tab when asked for
      e.preventDefault();
      focus(a.parentElement.dataset.row);
    }));
    Object.entries(mark).forEach(([k, e]) => link.wire(e, () => ({ keys: [k], ids: [], card: null })));
  });
})();
