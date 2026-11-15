// Tiles over one shared detail panel (Podněty, a street): a tile opens its detail in place and
// closes the others; a click on the open tile closes it. Without JS each tile is a link to
// ?detail=…, which the server renders open. Tiles: [data-pd-tile=key] with aria-expanded;
// details: [data-pd-detail=key]. With data-kpi-remember="name" on the tiles' container the page
// remembers the last open tile (this browser only; an explicit ?detail= in the address wins).
(function () {
  const tiles = document.querySelectorAll("[data-pd-tile]");
  const details = document.querySelectorAll("[data-pd-detail]");
  const box = document.querySelector("[data-kpi-remember]");
  const store = box ? "kpi-" + box.dataset.kpiRemember : null;
  const show = (key) => {
    tiles.forEach((x) => x.setAttribute("aria-expanded", String(x.dataset.pdTile === key)));
    details.forEach((d) => (d.hidden = d.dataset.pdDetail !== key));
  };
  const remember = (key) => { if (store) try { localStorage.setItem(store, key); } catch (e) { /* private window */ } };
  tiles.forEach((t) => {
    t.setAttribute("role", "button");
    t.addEventListener("click", (e) => {
      e.preventDefault();
      const key = t.dataset.pdTile, open = t.getAttribute("aria-expanded") !== "true";
      show(open ? key : null);
      remember(open ? key : "zadny");
      // the open tile stays out of the address: it is a view, not something to link to
    });
    t.addEventListener("keydown", (e) => { if (e.key === " ") { e.preventDefault(); t.click(); } });
  });
  if (store && !new URLSearchParams(location.search).has("detail")) {
    let key = null;
    try { key = localStorage.getItem(store); } catch (e) { /* private window */ }
    if (key === "zadny") show(null);
    else if (key && [...tiles].some((t) => t.dataset.pdTile === key)) show(key);
  }
})();
