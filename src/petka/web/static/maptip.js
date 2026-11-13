// The maps' tooltip (CSS .ak-tip): a white card hung on a marker or a zero-size anchor, shown
// while it is .on or focused. Shared by aktualne.js (the front page) and cisteni.js (the
// blokové čištění overview).
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
  // the tooltip goes to the left (.ak-l) where it would run off the map's right `edge` or over
  // the `box` (a DOMRect laid over the map)
  side(e, edge, box) {
    const at = e.getBoundingClientRect(), t = e.querySelector(".ak-tip");
    const end = at.right + 30 + (t ? t.offsetWidth : 230);
    e.classList.toggle("ak-l", end > edge - 8 || !!(box && end > box.left && at.top < box.bottom + 40));
  },
};
