// The maps' tooltip (CSS .ak-tip): a white card hung on a marker or a zero-size anchor, shown
// while it is .on or focused, and its card variant (.ak-card, placed by `place`). Used by the
// portal's map module petkamap.js and the pages on it (aktualne.js, cisteni.js, podnety.js,
// ulice.js).
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
  // the card variant (.ak-tip.ak-card), for a point with more to say: c = {photo, alt, title,
  // place, text, facts: [[term, value, cls]], href, link}. Everything goes in as text. The
  // photo hides itself when it fails; `onresize` runs when the card's height changes (photo
  // loaded, description opened) so its owner can place it again.
  card(c, onresize) {
    const t = document.createElement("div");
    t.className = "ak-tip ak-card";
    const add = (parent, tag, cls, text) => {
      const x = document.createElement(tag);
      if (cls) x.className = cls;
      if (text != null) x.textContent = text;
      parent.appendChild(x);
      return x;
    };
    if (c.photo) {
      const img = add(t, "img");
      img.loading = "lazy";
      img.decoding = "async";
      img.alt = c.alt || "";
      img.referrerPolicy = "no-referrer";
      img.addEventListener("load", () => onresize && onresize());
      img.addEventListener("error", () => { img.remove(); if (onresize) onresize(); });
      img.src = c.photo;
    }
    const b = add(t, "div", "ak-card-b");
    add(b, "b", "", c.title);
    if (c.place) add(b, "span", "", c.place);
    if (c.text) {
      const q = add(b, "p", "ak-card-q", "„" + c.text + "“");
      const more = add(b, "button", "ak-card-more", "celý popis");
      more.type = "button";
      more.hidden = true;
      more.addEventListener("click", () => {
        const open = q.classList.toggle("open");
        more.textContent = open ? "méně" : "celý popis";
        more.setAttribute("aria-expanded", String(open));
        if (onresize) onresize();
      });
      // only a longer description gets the toggle; measured once the card is in the page
      t.fit = () => { more.hidden = !(q.classList.contains("open") || q.scrollHeight > q.clientHeight + 1); };
    }
    if (c.facts && c.facts.length) {
      const dl = add(b, "dl");
      c.facts.forEach(([term, value, cls]) => {
        const row = add(dl, "div");
        add(row, "dt", "", term);
        add(row, "dd", cls || "", value);
      });
    }
    if (c.href) {
      const a = add(b, "a", "", c.link || "Otevřít");
      a.href = c.href;
      a.target = "_blank";
      a.rel = "noopener";
    }
    return t;
  },
  // where a card goes in its positioned box (w × h px) for a point at (x, y): to the right of
  // the point, to the left near the right edge; on a box too narrow for either, under the
  // point (over it near the bottom); always clamped inside the box where it fits
  place(card, x, y, w, h) {
    const cw = card.offsetWidth, ch = card.offsetHeight, gap = 16, m = 8;
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    let left, top;
    if (x + gap + cw <= w - m) left = x + gap;
    else if (x - gap - cw >= m) left = x - gap - cw;
    if (left !== undefined) {
      top = clamp(y - ch / 2, m, h - ch - m);
    } else {
      left = clamp(x - cw / 2, m, w - cw - m);
      top = y + gap + ch <= h - m ? y + gap : y - gap - ch >= m ? y - gap - ch : clamp(y - ch / 2, m, h - ch - m);
    }
    // a point off the map (a row whose report lies outside the view) still gets its card inside
    card.style.left = Math.round(Math.max(m, Math.min(left, w - cw - m))) + "px";
    card.style.top = Math.round(Math.max(m, Math.min(top, h - ch - m))) + "px";
  },
};
