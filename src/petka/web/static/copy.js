// <button data-copy="text">: copy the text to the clipboard (reviewers' preview of the cards)
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-copy]");
  if (!b) return;
  const text = b.dataset.copy, label = b.textContent;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const t = Object.assign(document.createElement("textarea"), { value: text });
    document.body.append(t); t.select(); document.execCommand("copy"); t.remove();
  }
  b.textContent = "Zkopírováno";
  setTimeout(() => (b.textContent = label), 1500);
});
