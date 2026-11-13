// The maps' tooltip (CSS .ak-tip): a white card hung on a marker or a zero-size anchor, shown
// while it is .on or focused. Shared by aktualne.js (the front page) and cisteni.js (the
// blokové čištění maps).
window.mapTip = {
  // street in bold, what it is, when (the dates line); the element's aria-label says the same
  make(street, what, when) {
    const t = document.createElement("span");
    t.className = "ak-tip";
    t.setAttribute("aria-hidden", "true");
    [["b", street], ["span", what], ["span", when]].forEach(([tag, text], i) => {
      if (!text) return;
      const x = document.createElement(tag);
      if (i === 2) x.className = "ak-tw";
      x.textContent = text;
      t.appendChild(x);
    });
    return t;
  },
  // an area's marker box (a parkoviště or a vnitroblok, cleaned whole): a dashed square, like
  // the legend's; the element goes into an .ak-mk
  area() {
    const NS = "http://www.w3.org/2000/svg";
    const i = document.createElement("i"), svg = document.createElementNS(NS, "svg"), r = document.createElementNS(NS, "rect");
    svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("width", "14"); svg.setAttribute("height", "14");
    svg.setAttribute("aria-hidden", "true");
    Object.entries({ x: 2, y: 2, width: 12, height: 12, rx: 1, fill: "none", stroke: "currentColor",
                     "stroke-width": 1.8, "stroke-dasharray": "3 2" }).forEach(([k, v]) => r.setAttribute(k, v));
    svg.appendChild(r);
    i.appendChild(svg);
    return i;
  },
  // the tooltip goes to the left (.ak-l) where it would run off the map's right `edge` or over
  // the `box` (a DOMRect laid over the map)
  side(e, edge, box) {
    const at = e.getBoundingClientRect(), t = e.querySelector(".ak-tip");
    const end = at.right + 30 + (t ? t.offsetWidth : 230);
    e.classList.toggle("ak-l", end > edge - 8 || !!(box && end > box.left && at.top < box.bottom + 40));
  },
};
