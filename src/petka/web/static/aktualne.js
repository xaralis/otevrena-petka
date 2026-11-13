// The front page's „Aktuálně“ (the map is petkamap.js): this week's blokové čištění grey, the
// street pointed at (or its day in the box) ink with its tooltip on an anchor (an area is a
// marker with a dashed square, its outline drawn only while pointed at), and úřední deska
// notices naming a street as markers. Rows of the two boxes point at their features; pointing
// shows, a click or a tap pins (phones have no hover), a click elsewhere on the map unpins.
// Data: <script id=…> from ulice/web.py home().
(function () {
  const el = document.querySelector("[data-ak-map]");
  const P = window.petkaMap;
  if (!el || !P || !P.ok() || !window.mapTip) return;
  const data = JSON.parse(document.getElementById(el.dataset.inline).textContent);
  const stage = el.closest(".ak");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  P.create(el, { controls: "bottom-right" }).then((map) => {
    const cl = P.cleaning(map, { id: "ak-cl", data: data.lines, scheme: "grey", by: "key", hit: 22, fade: !reduce, areas: "outline",
                                 show: ["!", ["get", "area"]] });
    const keysOf = {};
    data.lines.features.forEach((f) => (keysOf[f.properties.sid] ||= []).push(f.properties.key));
    const anchor = P.anchors(map, data.anchors.map((a) => ({ ...a, title: a.street, what: a.what || "Blokové čištění" })), { key: "sid" });
    const mark = P.marks(map, data.marks.map((m) => ({ ...m, title: m.street })), { icons: el.dataset.icons, animate: !reduce });

    // a state: the elements lit and the places' keys
    const cleaned = (sid) => ({ els: [anchor[sid]].filter(Boolean), keys: keysOf[sid] || [] });
    const day = (i, row) => { const d = data.days[i]; return { els: [row, ...d.sids.map((s) => anchor[s]).filter(Boolean)], keys: d.keys }; };
    const one = (id, row) => ({ els: [row, mark[id]].filter(Boolean), keys: [] });
    const same = (a, b) => a.els.length && a.els[0] === b.els[0] && a.keys.join() === b.keys.join();

    const link = P.linker((st) => {
      stage.querySelectorAll(".on").forEach((e) => e.classList.remove("on", "ak-l"));
      cl.lit(st ? st.keys : []);
      if (!st) return;
      const rbox = stage.querySelector(".ak-box-r");
      P.light(st.els, el.getBoundingClientRect().right, rbox && !P.narrow() ? rbox.getBoundingClientRect() : null);
    }, { same, escape: false });

    map.on("mousemove", cl.hit, (e) => { map.getCanvas().style.cursor = "pointer"; link.hover(cleaned(e.features[0].properties.sid)); });
    map.on("mouseleave", cl.hit, () => { map.getCanvas().style.cursor = ""; link.leave(); });
    map.on("click", (e) => {
      if (e.originalEvent.target.closest && e.originalEvent.target.closest(".ak-mk, .ak-cla")) return;
      const f = map.queryRenderedFeatures(e.point, { layers: [cl.hit] })[0];
      const st = f ? cleaned(f.properties.sid) : null;
      // a stretch opens its street's cleaning page like a marker opens its notice: at once on
      // wide screens, on phones with a second tap
      const a = f && anchor[f.properties.sid];
      if (a && a.href && (!P.narrow() || link.sameAsPinned(st))) { window.location.href = a.href; return; }
      if (st) link.pin(st, true); else link.close();
    });
    Object.entries(mark).forEach(([id, e]) => link.wire(e, () => one(id), { pins: true }));
    Object.entries(anchor).forEach(([sid, e]) => link.wire(e, () => cleaned(sid), { pins: true }));
    stage.querySelectorAll("[data-day]").forEach((r) => link.wire(r, () => day(+r.dataset.day, r), { pins: true }));
    stage.querySelectorAll("[data-mark]").forEach((r) => link.wire(r, () => one(r.dataset.mark, r), { pins: true }));

    // everything in view, clear of the boxes on wide screens
    const side = (cls) => { const x = stage.querySelector(cls); return x ? x.offsetWidth + 40 : 40; };
    const pad = P.narrow() ? 28 : { top: 40, bottom: 40, left: side(".ak-box-l"), right: side(".ak-box-r") };
    P.fit(map, [...data.lines.features, ...data.marks], { padding: pad, maxZoom: 15.5 });
  });
})();
