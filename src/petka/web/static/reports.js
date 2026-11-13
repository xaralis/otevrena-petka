// Podněty on a map, shared by podnety.js (the whole obvod) and ulice.js (one street):
//   images   a single report is a 14 px circle with an ink border, white or red-hatched while it
//            waits; a cluster a white disc sized by the count with a hatched wedge for the share
//            that waits and the count inside (canvas images, made on demand)
//   layers   the two symbol layers over a clustered GeoJSON source of stats.points features
//   card     the report's card (mapTip.card): photo, what, description, nahlášeno / odpověď
//            úřadu / stav (Dej Tip's word, red while it waits) / čeká, „Otevřít na Dej Tipu“
// A feature's properties: id, o (outcome), w (status word), c (category), s (street), t, a
// (reported, first answer, ISO), d (description), p (photo), wd (days waiting).
window.reportMap = (function () {
  const INK = "#191c1f", RED = "#de091c", PINK = "#f4a3aa";
  const DETAIL = "https://amg.dejtip.eu/pardubice/?id=";

  // the hatch of .pending-alert, at pixelRatio 2: pink with red stripes 3 px wide every 6 px
  function hatch(g, size) {
    g.fillStyle = PINK; g.fillRect(0, 0, size, size);
    g.strokeStyle = RED; g.lineWidth = 6;
    for (let x = -size; x < 2 * size; x += 12) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x + size, size); g.stroke(); }
  }
  function canvas(css) {
    const c = document.createElement("canvas");
    c.width = c.height = css * 2;
    return [c, c.getContext("2d")];
  }
  function point(waiting) {
    const [, g] = canvas(18), m = 18;
    g.save(); g.beginPath(); g.arc(m, m, 14, 0, 2 * Math.PI); g.clip();
    if (waiting) hatch(g, 36); else { g.fillStyle = "#fff"; g.fill(); }
    g.restore();
    g.beginPath(); g.arc(m, m, 13, 0, 2 * Math.PI); g.lineWidth = 4; g.strokeStyle = INK; g.stroke();
    return g.getImageData(0, 0, 36, 36);
  }
  // a cluster of n, w of them waiting: radius 10 + 1.7 √n px (radius() below)
  const radius = (n) => 10 + 1.7 * Math.sqrt(n);
  function cluster(n, w) {
    const r = radius(n), css = Math.ceil(2 * r + 4), [, g] = canvas(css), m = css, R = 2 * r;
    g.beginPath(); g.arc(m, m, R, 0, 2 * Math.PI); g.fillStyle = "#fff"; g.fill();
    if (w > 0) {
      g.save(); g.beginPath(); g.moveTo(m, m);
      g.arc(m, m, R, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * Math.min(1, w / n)); g.closePath(); g.clip();
      hatch(g, 2 * css); g.restore();
    }
    g.beginPath(); g.arc(m, m, R - 2, 0, 2 * Math.PI); g.lineWidth = 4; g.strokeStyle = INK; g.stroke();
    g.beginPath(); g.arc(m, m, R - 10, 0, 2 * Math.PI); g.fillStyle = "#fff"; g.fill();
    g.fillStyle = INK; g.font = '800 23px "Bricolage Grotesque", system-ui, sans-serif';
    g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(String(n), m, m + 1);
    return g.getImageData(0, 0, 2 * css, 2 * css);
  }

  // the images under `prefix`: -pt, -pt-w and -c-<n>-<waiting> on demand
  function images(map, prefix) {
    map.addImage(prefix + "-pt", point(false), { pixelRatio: 2 });
    map.addImage(prefix + "-pt-w", point(true), { pixelRatio: 2 });
    const re = new RegExp("^" + prefix + "-c-(\\d+)-(\\d+)$");
    map.on("styleimagemissing", (e) => {
      const m = re.exec(e.id);
      if (m && !map.hasImage(e.id)) map.addImage(e.id, cluster(+m[1], +m[2]), { pixelRatio: 2 });
    });
  }
  // the source's options for clustering with the waiting count
  const clustered = { cluster: true, clusterRadius: 44, clusterMaxZoom: 16,
                      clusterProperties: { waiting: ["+", ["case", ["==", ["get", "o"], "ceka"], 1, 0]] } };
  // the layers <prefix>-pt (single reports) and <prefix>-cl (clusters) over `source`
  function layers(map, source, prefix) {
    const solo = { "icon-allow-overlap": true, "icon-ignore-placement": true };
    map.addLayer({ id: prefix + "-pt", type: "symbol", source, filter: ["!", ["has", "point_count"]],
                   layout: { ...solo, "icon-image": ["case", ["==", ["get", "o"], "ceka"], prefix + "-pt-w", prefix + "-pt"],
                             "symbol-sort-key": ["case", ["==", ["get", "o"], "ceka"], 1, 0] } });
    map.addLayer({ id: prefix + "-cl", type: "symbol", source, filter: ["has", "point_count"],
                   layout: { ...solo, "icon-image": ["concat", prefix + "-c-", ["to-string", ["get", "point_count"]], "-",
                                                     ["to-string", ["get", "waiting"]]],
                             "symbol-sort-key": ["get", "point_count"] } });
  }

  // --- words ---
  const plural = (n, one, few, many) => (n === 1 ? one : n >= 2 && n <= 4 ? few : many);
  const thisYear = new Date().getFullYear();
  function dm(iso) { const [y, mo, d] = iso.slice(0, 10).split("-").map(Number); return `${d}. ${mo}.` + (y !== thisYear ? ` ${y}` : ""); }
  function when(iso) {
    const h = +iso.slice(11, 13), mi = iso.slice(14, 16);
    return `${dm(iso)} ${[2, 3, 4, 12, 13, 14, 20, 21, 22, 23].includes(h) ? "ve" : "v"} ${h}:${mi}`;
  }
  function waiting(p) {
    if (p.o !== "ceka") return null;
    const n = p.wd || 0;
    return n < 1 ? "od dneška" : `${n} ${plural(n, "den", "dny", "dní")}`;
  }
  // the card's status is Dej Tip's own word (red while it waits); how long it waits is a fact of its own
  function card(p, onresize) {
    const facts = [["nahlášeno", when(p.t)]];
    if (p.a) facts.push(["odpověď úřadu", when(p.a)]);
    facts.push(["stav", p.w, p.o === "ceka" ? "st-no" : ""]);
    const long = waiting(p);
    if (long) facts.push(["čeká", long]);
    return window.mapTip.card({
      photo: p.p, alt: `Fotka z podnětu: ${p.c}${p.s ? ", " + p.s : ""}`, title: p.c, place: p.s, text: p.d,
      facts, href: DETAIL + p.id, link: "Otevřít na Dej Tipu",
    }, onresize);
  }

  return { INK, DETAIL, images, clustered, layers, radius, card, plural, dm, when };
})();
