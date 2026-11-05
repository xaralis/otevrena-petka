// Úřední deska pro lidi: a plain-language card turns over to the office's own wording in place.
// Click (touch, keyboard) toggles; with a mouse, pointing at "Úřední znění" turns it and leaving
// the card turns it back. Without JS the back stays hidden (the notice page has the original).
document.querySelectorAll(".card-flip").forEach((box) => {
  const front = box.querySelector(".card-front"), back = box.querySelector(".card-back");
  const toBack = front.querySelector(".flip"), toFront = back.querySelector(".flip");
  const set = (on) => {
    box.classList.toggle("flipped", on);
    front.inert = on; back.inert = !on;
    front.setAttribute("aria-hidden", on); back.setAttribute("aria-hidden", !on);
    toBack.setAttribute("aria-expanded", on);
  };
  back.hidden = false;
  box.classList.add("ready");
  set(false);
  toBack.addEventListener("click", () => { set(true); toFront.focus({ preventScroll: true }); });
  toFront.addEventListener("click", () => { set(false); toBack.focus({ preventScroll: true }); });
  if (matchMedia("(hover: hover) and (pointer: fine)").matches) {
    toBack.addEventListener("mouseenter", () => set(true));
    box.closest("li").addEventListener("mouseleave", () => set(false));
  }
});
