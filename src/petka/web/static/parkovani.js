// Parkování: a link [data-pk-part] in a row (a table's <tr>, or a list's <li data-pk-row>) opens the
// area's or the lot's detail under it and closes the other open one there; a second click closes it. The detail is
// the part the link's data-pk-part names (/verejny-prostor/parkovani/oblast/{id} or /parkoviste/{id}).
// Without JS the link's href opens the same detail on the page itself (?oblast= / ?parkoviste=).
(function () {
  const close = (row) => {
    const link = row.previousElementSibling && row.previousElementSibling.querySelector("a[data-pk-part]");
    if (link) link.setAttribute("aria-expanded", "false");
    row.remove();
  };
  document.addEventListener("click", async (e) => {
    const a = e.target.closest("a[data-pk-part]");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    const row = a.closest("[data-pk-row], tr");
    if (!row) return;
    e.preventDefault();
    const wasOpen = a.getAttribute("aria-expanded") === "true";
    row.parentElement.querySelectorAll(":scope > .pk-open").forEach(close);
    if (wasOpen) return;
    a.setAttribute("aria-expanded", "true");
    const isTr = row.tagName === "TR";
    const tr = document.createElement(isTr ? "tr" : "li");
    tr.className = "pk-open";
    const td = isTr ? document.createElement("td") : tr;
    if (isTr) { td.colSpan = row.children.length; tr.appendChild(td); }
    td.innerHTML = '<p class="note">Načítám…</p>';
    row.after(tr);
    try {
      const r = await fetch(a.dataset.pkPart);
      if (!r.ok) throw new Error(String(r.status));
      td.innerHTML = await r.text();
    } catch (err) {
      td.innerHTML = '<p class="note">Detail se nepodařilo načíst.</p>';
    }
  });
})();
