// A link [data-part] in a row (a table's <tr>, or a list's <li data-part-row>) opens a detail under
// the row and closes the other open one there; a second click closes it. The detail is the HTML part
// at the link's data-part URL (parkování: an area or a lot; rozpočet: a položka over the years).
// Without JS the link's href opens the same detail on the page itself.
(function () {
  const close = (row) => {
    const link = row.previousElementSibling && row.previousElementSibling.querySelector("a[data-part]");
    if (link) link.setAttribute("aria-expanded", "false");
    row.remove();
  };
  document.addEventListener("click", async (e) => {
    const a = e.target.closest("a[data-part]");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    const row = a.closest("[data-part-row], tr");
    if (!row) return;
    e.preventDefault();
    const wasOpen = a.getAttribute("aria-expanded") === "true";
    row.parentElement.querySelectorAll(":scope > .part-open").forEach(close);
    if (wasOpen) return;
    a.setAttribute("aria-expanded", "true");
    const isTr = row.tagName === "TR";
    const tr = document.createElement(isTr ? "tr" : "li");
    tr.className = "part-open";
    const td = isTr ? document.createElement("td") : tr;
    if (isTr) { td.colSpan = row.children.length; tr.appendChild(td); }
    td.innerHTML = '<p class="note">Načítám…</p>';
    row.after(tr);
    try {
      const r = await fetch(a.dataset.part);
      if (!r.ok) throw new Error(String(r.status));
      td.innerHTML = await r.text();
    } catch (err) {
      td.innerHTML = '<p class="note">Detail se nepodařilo načíst.</p>';
    }
  });
})();
