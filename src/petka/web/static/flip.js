// Úřední deska pro lidi: a plain-language card turns over to the office's own wording in place,
// by a click on the button under the č. j. (only a click: turning on hover was too jumpy).
// Without JS there is no button and the back stays hidden (the notice page has the original).
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
  box.classList.add("ready");        // faces stacked, back turned away – without animating there
  set(false);
  requestAnimationFrame(() => requestAnimationFrame(() => box.classList.add("animate")));
  button.addEventListener("click", () => set(!box.classList.contains("flipped")));
});
