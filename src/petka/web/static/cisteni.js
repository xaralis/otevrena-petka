// Čištění ulic: the maps (petkamap.js) and the calendar picker.
// <div data-cl-map="all" data-src="/api/v1/cisteni" data-today="YYYY-MM-DD" data-anchors="id">
// colours the obvod's places by their next cleaning (≤ 7 days red, ≤ 14 ink, later grey,
// approximate dashed) and behaves like the front page's map (aktualne.js): pointing at a stretch
// inks it and shows its tooltip on a focusable zero-size anchor, a click opens its street (on
// phones the second tap), and the rows beside the map ([data-cl-key]) light up with their
// stretches both ways; a click on a row moves the map to its stretch. An area (a parkoviště or a vnitroblok, a polygon whose shape is our
// estimate) is a marker at a point inside; its outline shows dashed only while pointed at.
// <div data-cl-map="street" data-inline="id"> shows one street: its line in ink and, thicker,
// the stretches still to be cleaned on it; no tooltips (the dates are in the table).
// The picker remembers its streets in localStorage; without JS the form goes to /verejny-prostor/blokove-cisteni/kalendar.
(function () {
  const P = window.petkaMap;
  const INK = "#191c1f", GREY = "#8a9097";

  // --- maps -----------------------------------------------------------------------------------
  if (P && P.ok()) document.querySelectorAll("[data-cl-map]").forEach(setup);

  function setup(el) {
    const all = el.dataset.clMap === "all";
    const data = el.dataset.src
      ? fetch(el.dataset.src).then((r) => r.json())
      : Promise.resolve(JSON.parse(document.getElementById(el.dataset.inline).textContent));
    P.create(el, { cooperative: !all }).then(async (map) => {
      const fc = await data;
      // the overview shows only what is still to come this year (the API is asked from today)
      fc.features = fc.features.filter((f) => f.geometry && (!all || f.properties.next));
      if (all) {
        P.colourByDate(fc, el.dataset.today);
        const cl = P.cleaning(map, { id: "cl", data: fc, scheme: "props", by: "key", hit: 16, areas: "outline" });
        P.fit(map, fc.features, { padding: 20 });
        tips(map, el, fc, cl);
        return;
      }
      // one street: its line in ink (the base map's road where it has one), the stretches thicker
      const road = fc.features.find((f) => f.properties.kind === "street");
      const stretches = fc.features.filter((f) => f.properties.kind !== "street" && !/Polygon/.test(f.geometry.type));
      stretches.forEach((f) => Object.assign(f.properties, { color: INK, width: 6, dash: false }));
      const w3 = ["interpolate", ["linear"], ["zoom"], 12, 2.25, 15, 3, 18, 5.4];
      const sl = P.street(map, { id: "cl-street", geometry: road && road.geometry, name: el.dataset.name,
                                 paint: { "line-color": INK, "line-width": w3 },
                                 casing: ["interpolate", ["linear"], ["zoom"], 12, 4.5, 15, 6, 18, 10.8],
                                 refit: (b) => P.fit(map, [...(b ? [b.toArray()] : []), ...stretches]) });
      const cl = P.cleaning(map, { id: "cl", data: { type: "FeatureCollection", features: stretches }, scheme: "props", by: "key", areas: "outline" });
      P.belowLabels(map, sl);
      sl.forEach((id) => map.moveLayer(id, cl.layers[0]));      // the street under its stretches
      P.fit(map, fc.features);
    });
  }

  // the overview's tooltips and highlights, the same way as aktualne.js: pointing shows, a click
  // or a tap pins (phones have no hover), a click elsewhere on the map unpins
  function tips(map, el, fc, cl) {
    const strip = {};
    fc.features.forEach((f) => (strip[f.properties.key] = f.properties.color));
    const src = document.getElementById(el.dataset.anchors);
    const list = src ? JSON.parse(src.textContent) : [];
    const els = P.anchors(map, list.map((a, i) => ({ ...a, i, title: a.street, strip: a.area ? strip[a.keys[0]] || GREY : null })), { key: "i" });
    // a stretch: its places' keys (both sides of a street drawn as one line), its anchor, its rows
    const of = {};
    list.forEach((a, i) => { const s = { keys: a.keys, anchor: els[i], rows: [] }; a.keys.forEach((k) => (of[k] = s)); });
    document.querySelectorAll("[data-cl-key]").forEach((r) => {
      const k = r.dataset.clKey;
      (of[k] ||= { keys: [k], anchor: null, rows: [] }).rows.push(r);   // a place not on the map lights only itself
    });

    let shown;
    const link = P.linker((s) => {
      if (shown === s) return;
      shown = s;
      el.querySelectorAll(".ak-cla.on, .ak-mk.on").forEach((e) => e.classList.remove("on", "ak-l"));
      document.querySelectorAll("[data-cl-key].on").forEach((e) => e.classList.remove("on"));
      cl.lit(s ? s.keys : []);
      if (!s) return;
      s.rows.forEach((r) => r.classList.add("on"));
      P.light([s.anchor], el.getBoundingClientRect().right);
    }, { escape: false });

    const at = (p) => { const f = map.queryRenderedFeatures(p, { layers: [cl.hit] })[0]; return f ? of[f.properties.key] || null : null; };
    map.on("mousemove", (e) => {
      // a marker (an area) handles its own pointing
      if (e.originalEvent.target.closest && e.originalEvent.target.closest(".ak-mk")) return;
      const s = at(e.point);
      map.getCanvas().style.cursor = s ? "pointer" : "";
      if (s) link.hover(s); else link.leave();
    });
    map.on("mouseout", () => { map.getCanvas().style.cursor = ""; link.leave(); });
    map.on("click", (e) => {
      if (e.originalEvent.target.closest && e.originalEvent.target.closest(".ak-cla, .ak-mk")) return;
      const s = at(e.point), a = s && s.anchor;
      // a stretch opens its street's page: at once on wide screens, on phones with a second tap
      if (a && a.href && (!P.narrow() || link.pinned === s)) { window.location.href = a.href; return; }
      if (s) link.pin(s, true); else link.close();
    });
    new Set(Object.values(of)).forEach((s) => {
      if (s.anchor) link.wire(s.anchor, () => s, { pins: true });
      // pointing at a row or focusing it shows its stretch; a click moves the map to it and keeps
      // it shown (its tooltip links to the street); a row whose place is not on the map stays a link
      s.rows.forEach((r) => link.wire(r, () => s, { within: true }));
      const feats = fc.features.filter((f) => s.keys.includes(f.properties.key));
      if (!feats.length) return;
      s.rows.forEach((r) => r.querySelector("a").addEventListener("click", (e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;      // a new tab when asked for
        e.preventDefault();
        P.fit(map, feats, { duration: 500, maxZoom: 17, padding: 70 });
        if (P.narrow()) el.scrollIntoView({ behavior: "smooth", block: "center" });
        map.once("moveend", () => link.pin(s));
      }));
    });
  }

  // --- the calendar picker --------------------------------------------------------------------
  const form = document.querySelector("[data-cl-pick]");
  if (!form) return;
  const names = JSON.parse(document.getElementById("cl-names").textContent);   // {slug: name}
  const bySlugName = Object.fromEntries(Object.entries(names).map(([s, n]) => [fold(n), s]));
  const chips = form.querySelector("[data-cl-chips]"), add = form.querySelector(".chip-add");
  const go = form.querySelector("[data-cl-go]"), https = form.querySelector("[data-cl-https]");
  const KEY = "cisteni-ulice";
  let picked = [];
  try { picked = JSON.parse(localStorage.getItem(KEY) || "[]").filter((s) => s in names); } catch (e) { picked = []; }
  const checked = new Set(picked);

  function fold(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim(); }
  function plural(n, one, few, many) { return n === 1 ? one : n >= 2 && n <= 4 ? few : many; }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(picked.filter((s) => checked.has(s)))); } catch (e) { /* private window */ } }
  function url(scheme) {
    return scheme + "://" + location.host + "/verejny-prostor/blokove-cisteni/kalendar.ics?ulice=" + picked.filter((s) => checked.has(s)).join(",");
  }
  function render() {
    chips.textContent = "";
    picked.forEach((s) => {
      const label = document.createElement("label"), box = document.createElement("input");
      label.className = "chip";
      box.type = "checkbox"; box.name = "ulice"; box.value = s; box.checked = checked.has(s);
      box.addEventListener("change", () => { box.checked ? checked.add(s) : checked.delete(s); save(); update(); });
      label.append(box, " " + names[s]);
      chips.append(label);
    });
    update();
  }
  function update() {
    const n = picked.filter((s) => checked.has(s)).length;
    go.textContent = n ? `Přidat ${n} ${plural(n, "ulici", "ulice", "ulic")} do kalendáře` : "Vyberte ulice";
    go.setAttribute("aria-disabled", n ? "false" : "true");
    https.hidden = !n;
    if (n) https.href = url(location.protocol.replace(":", ""));
  }
  function addName() {
    const s = bySlugName[fold(add.value)];
    if (!s) return false;
    if (!picked.includes(s)) picked.push(s);
    checked.add(s);
    add.value = "";
    save();
    render();
    return true;
  }
  add.addEventListener("change", addName);
  add.addEventListener("keydown", (e) => { if (e.key === "Enter" && addName()) e.preventDefault(); });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    addName();
    if (picked.some((s) => checked.has(s))) location.href = url("webcal");
  });
  render();
})();
