/** Nearest overflow scroller, then the document. */
export function findScrollParent(el: HTMLElement): HTMLElement {
  let p = el.parentElement;
  while (p) {
    const overflowY = getComputedStyle(p).overflowY;
    if (overflowY === "auto" || overflowY === "scroll") return p;
    p = p.parentElement;
  }
  const doc = document.scrollingElement;
  return doc instanceof HTMLElement ? doc : document.documentElement;
}

function clampScrollTop(scroller: HTMLElement, next: number): void {
  const max = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
  scroller.scrollTop = Math.max(0, Math.min(max, next));
}

/** Move `el` inside its scroll parent only (does not chain to the window). */
export function alignInScrollParent(
  el: HTMLElement,
  block: "start" | "end" | "nearest",
): void {
  const scroller = findScrollParent(el);
  if (scroller === el) return;
  const s = scroller.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  let delta = 0;
  if (block === "start") delta = r.top - s.top;
  else if (block === "end") delta = r.bottom - s.bottom;
  else if (r.top < s.top) delta = r.top - s.top;
  else if (r.bottom > s.bottom) delta = r.bottom - s.bottom;
  if (delta === 0) return;
  clampScrollTop(scroller, scroller.scrollTop + delta);
}

/**
 * Tall panels (trajectory / 70vh file split) sit on the bottom of the
 * scrollport. Short panels use nearest. Avoids UA focus `center` jumps.
 */
export function revealTallPanel(el: HTMLElement): void {
  const scroller = findScrollParent(el);
  if (scroller === el) return;
  const tall = el.getBoundingClientRect().height >= scroller.clientHeight * 0.55;
  alignInScrollParent(el, tall ? "end" : "nearest");
}
