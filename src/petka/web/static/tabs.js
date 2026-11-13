// Tabs over the sections of a page (Data a API): <nav data-tabs> with links to #id, panels with
// data-panel="id". Without JS every panel shows; with it one at a time, the one the address names
// (#id), so /data#uredni-deska still lands on its section.
(function () {
  const nav = document.querySelector("[data-tabs]");
  if (!nav) return;
  const links = Array.from(nav.querySelectorAll("[data-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-panel]"));
  const ids = links.map((a) => a.dataset.tab);
  document.body.dataset.tabsOn = "";      // the tab names the panel: its own heading only for screen readers
  function show(id, push) {
    if (!ids.includes(id)) id = ids[0];
    panels.forEach((p) => (p.hidden = p.dataset.panel !== id));
    links.forEach((a) => (a.dataset.tab === id ? a.setAttribute("aria-current", "true") : a.removeAttribute("aria-current")));
    if (push) history.replaceState(null, "", "#" + id);
  }
  links.forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); show(a.dataset.tab, true); }));
  window.addEventListener("hashchange", () => { if (ids.includes(location.hash.slice(1))) show(location.hash.slice(1)); });
  show(location.hash.slice(1), false);
  // an address with #id lands on the tabs, not under them (the browser jumps to the panel)
  if (ids.includes(location.hash.slice(1))) requestAnimationFrame(() => nav.scrollIntoView({ block: "start" }));
})();
