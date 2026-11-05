// Úřední deska pro lidi: a plain-language card turns over to the office's own wording in place.
// The button under the č. j. does it: a click (touch, keyboard) toggles; with a mouse, pointing at
// the button turns the card for a look and leaving the row turns it back, unless it was clicked. Without JS there is no button and
// the back stays hidden (the notice page has the original).
document.querySelectorAll(".card-row").forEach((row) => {
  const box = row.querySelector(".card-flip"), button = row.querySelector(".flip");
  if (!box || !button) return;
  const front = box.querySelector(".card-front"), back = box.querySelector(".card-back");
  const set = (on) => {
    box.classList.toggle("flipped", on);
    row.classList.toggle("is-flipped", on);
    front.inert = on; back.inert = !on;
    front.setAttribute("aria-hidden", on); back.setAttribute("aria-hidden", !on);
    button.setAttribute("aria-pressed", on);
  };
  back.hidden = false;
  button.hidden = false;
  box.classList.add("ready");
  set(false);
  // pointing turns it for a look; a click keeps it as it is (pointing then clicking "Ukázat
  // originál" must not turn it straight back)
  let peek = false;
  button.addEventListener("click", () => {
    if (peek) { peek = false; return; }
    set(!box.classList.contains("flipped"));
  });
  if (matchMedia("(hover: hover) and (pointer: fine)").matches) {
    button.addEventListener("mouseenter", () => {
      if (!box.classList.contains("flipped")) { peek = true; set(true); }
    });
    row.addEventListener("mouseleave", () => { if (peek) { peek = false; set(false); } });
  }
});
