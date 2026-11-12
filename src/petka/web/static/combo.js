// Combobox (našeptávač): a text field that suggests values from a fixed list, styled like the
// portal instead of the browser's own <datalist> popup. Progressive enhancement: the markup is a
// plain <input list="…"> with a <datalist>; this script takes the options over, removes the
// `list` attribute and draws its own listbox (ARIA 1.2 combobox pattern).
//
//   <input class="… combo-input" list="cl-streets" data-combo>
//   <datalist id="cl-streets"><option value="Wolkerova">…</datalist>
//
// Choosing an option sets the input's value and fires "change" (and "combo-pick"), so callers
// keep listening to the input as before. Matching ignores case and diacritics, prefix first.
(function () {
  "use strict";
  const MAX = 8;
  const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  let seq = 0;

  function attach(input) {
    const dl = document.getElementById(input.getAttribute("list"));
    if (!dl) return;
    const values = [...dl.options].map((o) => o.value);
    const folded = values.map(fold);
    input.removeAttribute("list");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("autocomplete", "off");

    const wrap = document.createElement("div");
    wrap.className = "combo";
    input.parentNode.insertBefore(wrap, input);
    wrap.append(input);
    const list = document.createElement("ul");
    list.className = "combo-list";
    list.id = "combo-" + ++seq;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    wrap.append(list);
    input.setAttribute("aria-controls", list.id);
    if (input.closest(".band")) wrap.classList.add("combo-on-red");

    let shown = [], active = -1;

    function close() {
      list.hidden = true; active = -1; shown = [];
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }
    function mark(i) {
      active = i;
      [...list.children].forEach((li, j) => li.setAttribute("aria-selected", j === i ? "true" : "false"));
      if (i >= 0) { input.setAttribute("aria-activedescendant", list.children[i].id); list.children[i].scrollIntoView({ block: "nearest" }); }
      else input.removeAttribute("aria-activedescendant");
    }
    function pick(i) {
      input.value = shown[i];
      close();
      input.dispatchEvent(new Event("change", { bubbles: true }));
      input.dispatchEvent(new CustomEvent("combo-pick", { bubbles: true, detail: { value: input.value } }));
    }
    function open() {
      const q = fold(input.value);
      if (!q) return close();
      const starts = [], has = [];
      folded.forEach((f, i) => (f.startsWith(q) ? starts : f.includes(q) ? has : null)?.push(values[i]));
      shown = starts.concat(has).slice(0, MAX);
      if (!shown.length || (shown.length === 1 && fold(shown[0]) === q)) return close();
      list.textContent = "";
      shown.forEach((v, i) => {
        const li = document.createElement("li");
        li.id = list.id + "-" + i;
        li.className = "combo-opt";
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", "false");
        const at = fold(v).indexOf(q);
        li.append(v.slice(0, at));
        const b = document.createElement("b");
        b.textContent = v.slice(at, at + q.length);
        li.append(b, v.slice(at + q.length));
        li.addEventListener("mousedown", (e) => { e.preventDefault(); pick(i); });
        list.append(li);
      });
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      mark(-1);
    }

    input.addEventListener("input", open);
    input.addEventListener("blur", close);
    input.addEventListener("keydown", (e) => {
      if (list.hidden) { if (e.key === "ArrowDown") { open(); } return; }
      if (e.key === "ArrowDown") { e.preventDefault(); mark((active + 1) % shown.length); }
      else if (e.key === "ArrowUp") { e.preventDefault(); mark(active <= 0 ? shown.length - 1 : active - 1); }
      else if (e.key === "Enter" && active >= 0) { e.preventDefault(); e.stopImmediatePropagation(); pick(active); }
      else if (e.key === "Escape") { close(); }
    });
  }

  document.querySelectorAll("input[data-combo][list]").forEach(attach);
})();
