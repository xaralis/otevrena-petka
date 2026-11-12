// The phone menu: "Menu" opens the full-screen list of areas and pages, "Zavřít" or Escape
// closes it and focus goes back. Without JS both are links to #menu and #, and CSS shows the
// menu while it is the :target.
(function () {
  const menu = document.getElementById("menu");
  const open = document.querySelector("[data-menu-open]");
  const close = menu && menu.querySelector("[data-menu-close]");
  if (!menu || !open || !close) return;
  document.documentElement.classList.add("js-menu");      // from now on .open, not :target

  function set(on) {
    menu.classList.toggle("open", on);
    document.documentElement.classList.toggle("mm-on", on);
    open.setAttribute("aria-expanded", String(on));
    (on ? close : open).focus();
  }
  open.addEventListener("click", (e) => { e.preventDefault(); set(true); });
  close.addEventListener("click", (e) => {
    e.preventDefault();
    if (location.hash === "#menu") history.replaceState(null, "", location.pathname + location.search);
    set(false);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && menu.classList.contains("open")) set(false); });
  // a narrow window that grows wide closes it
  if (location.hash === "#menu") set(true);
  matchMedia("(min-width: 901px)").addEventListener("change", (m) => { if (m.matches && menu.classList.contains("open")) set(false); });
})();
