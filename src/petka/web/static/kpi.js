// Tiles over one shared detail panel (Podněty, a street): a tile opens its detail in place and
// closes the others; a click on the open tile closes it. Without JS each tile is a link to
// ?detail=…, which the server renders open. Tiles: [data-pd-tile=key] with aria-expanded;
// details: [data-pd-detail=key].
(function () {
  const tiles = document.querySelectorAll("[data-pd-tile]");
  const details = document.querySelectorAll("[data-pd-detail]");
  tiles.forEach((t) => {
    t.setAttribute("role", "button");
    t.addEventListener("click", (e) => {
      e.preventDefault();
      const key = t.dataset.pdTile, open = t.getAttribute("aria-expanded") !== "true";
      tiles.forEach((x) => x.setAttribute("aria-expanded", String(open && x === t)));
      details.forEach((d) => (d.hidden = !(open && d.dataset.pdDetail === key)));
      // the open tile stays out of the address: it is a view, not something to link to
    });
    t.addEventListener("keydown", (e) => { if (e.key === " ") { e.preventDefault(); t.click(); } });
  });
})();
