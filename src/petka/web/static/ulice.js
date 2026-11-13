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

  if (window.matchMedia("(max-width: 600px)").matches)
    document.querySelectorAll("input[data-short]").forEach((i) => (i.placeholder = i.dataset.short));

  const el = document.querySelector("[data-ul-map]");
  const P = window.petkaMap;
  if (!el || !P || !P.ok() || !window.mapTip) return;
  const data = JSON.parse(document.getElementById(el.dataset.inline).textContent);
  const stage = el.closest(".ul-akt");
  const wrap = el.parentElement;
  const sheet = stage.querySelector("[data-ul-sheet]");
  const reports = data.reports.features;
  const byId = new Map(reports.map((f) => [f.properties.id, f]));
  const idsOf = {};
  reports.forEach((f) => { if (f.properties.row) (idsOf[f.properties.row] ||= []).push(f.properties.id); });
  const list = document.querySelector("[data-ul-rows]");
  const rowEl = (k) => (list ? list.querySelector(`li[data-row="${k}"]`) : null);
  const ahead = (f) => !f.properties.past;

  // the street in view from the start (RÚIAN's line), the base map's road once it is loaded
  P.create(el, { bounds: P.bounds([data.street]) || undefined, fitBoundsOptions: { padding: 40, maxZoom: 17 }, font: true }).then((map) => {
    const sl = P.street(map, { id: "ul-street", geometry: data.street, name: el.dataset.name,
                               paint: { "line-color": P.INK, "line-opacity": 0.14, "line-width": ["interpolate", ["linear"], ["zoom"], 13, 8, 18, 22] },
                               refit: (b) => P.fit(map, [...(b ? [b.toArray()] : []), ...data.cleaning.features.filter(ahead)]) });
    const cl = P.cleaning(map, { id: "ul-cl", data: data.cleaning, scheme: "grey", by: "row", hit: 22, areas: "fill",
                                 show: ["==", ["get", "past"], false] });
    P.belowLabels(map, sl);
    sl.forEach((id) => map.moveLayer(id, cl.layers[0]));      // the street under the cleanings
    const rep = P.reports(map, { id: "ur", data: data.reports, wrap, sheet, owners: true });
    const anchor = P.anchors(map, data.anchors.map((a) => ({ ...a, what: a.text })), { key: "row", hidden: true });
    const mark = P.marks(map, data.marks.map((m) => ({ ...m, title: m.what, what: "Úřední deska" })), { icons: el.dataset.icons, key: "row" });

    // a state: {keys: [row keys], ids: [report ids outlined], card: a report's id or null}
    const fromRow = (k) => { const ids = idsOf[k] || []; return { keys: [k], ids, card: ids.length === 1 ? ids[0] : null }; };
    const fromReport = (id) => ({ keys: [byId.get(id).properties.row].filter(Boolean), ids: [id], card: id });
    const link = P.linker((st) => {
      stage.querySelectorAll(".on").forEach((e) => { if (e !== rep.card.el) e.classList.remove("on", "ak-l"); });
      const keys = st ? st.keys : [];
      cl.lit(keys);
      keys.forEach((k) => { const r = rowEl(k); if (r) r.classList.add("on"); });
      P.light(keys.flatMap((k) => [anchor[k], mark[k]]), el.getBoundingClientRect().right);
      rep.ring((st ? st.ids : []).map((id) => rep.owner(id)));
      if (st && st.card != null) rep.card.show(st.card, { enter: () => link.keep(), leave: () => link.leave() });
      else rep.card.hide();
    }, { delay: 250, within: () => [wrap, sheet, list] });
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
    if (list) list.querySelectorAll("li[data-row]").forEach((li) => link.wire(li.firstElementChild, () => fromRow(li.dataset.row)));
    // the control beside a row: the map moves to what the row is about and keeps it shown
    const featuresOf = (k) => [
      ...(idsOf[k] || []).map((id) => byId.get(id)),
      ...data.cleaning.features.filter((f) => f.properties.row === k),
      ...data.marks.filter((m) => m.row === k),
      ...data.anchors.filter((a) => a.row === k),
    ];
    if (list) list.querySelectorAll("[data-ul-pin]").forEach((b) => b.addEventListener("click", (e) => {
      e.preventDefault();
      const k = b.dataset.ulPin;
      P.fit(map, featuresOf(k), { duration: 500, maxZoom: 17.5, padding: 60 });
      if (window.matchMedia("(max-width: 900px)").matches) el.scrollIntoView({ behavior: "smooth", block: "center" });
      map.once("moveend", () => link.pin(fromRow(k)));
    }));
    Object.entries(mark).forEach(([k, e]) => link.wire(e, () => ({ keys: [k], ids: [], card: null })));
  });
})();
