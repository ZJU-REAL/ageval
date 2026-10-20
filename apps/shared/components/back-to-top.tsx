import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { ArrowUp } from "lucide-react";

import { Button } from "@ageval/shared/components/ui/button";
import { cn } from "@ageval/shared/lib/utils";

/** Upward travel before the control appears, and downward travel before it hides. */
const DIRECTION_PX = 32;
/** Already at the top of the scroller. The control has nothing to do. */
const TOP_PX = 64;
/** Ignore short widgets (menus, code blocks, the pace strip). */
const MIN_SCROLLER_PX = 240;

function contentScroller(node: EventTarget | null): HTMLElement | null {
  if (!(node instanceof HTMLElement)) return null;
  if (
    node.closest(
      "[role='dialog'], [role='listbox'], [data-ageval-menu], [data-radix-popper-content-wrapper]",
    )
  ) {
    return null;
  }
  if (node.id !== "main" && !node.closest("#main")) return null;
  const overflowY = getComputedStyle(node).overflowY;
  if (overflowY !== "auto" && overflowY !== "scroll") return null;
  if (node.id !== "main" && node.clientHeight < MIN_SCROLLER_PX) return null;
  if (node.scrollHeight <= node.clientHeight + TOP_PX) return null;
  return node;
}

export function BackToTop() {
  const { pathname } = useLocation();
  const [shown, setShown] = useState(false);
  const targetRef = useRef<HTMLElement | null>(null);
  const lastTop = useRef(new WeakMap<HTMLElement, number>());
  const accumRef = useRef({ px: 0, el: null as HTMLElement | null });

  useEffect(() => {
    setShown(false);
    accumRef.current = { px: 0, el: null };
    const main = document.getElementById("main");
    if (main) lastTop.current.set(main, main.scrollTop);
  }, [pathname]);

  useEffect(() => {
    function onScroll(event: Event) {
      const el = contentScroller(event.target);
      if (!el) return;
      const top = el.scrollTop;
      const prev = lastTop.current.get(el);
      lastTop.current.set(el, top);
      if (prev === undefined) return;
      const delta = top - prev;
      if (delta === 0) return;
      if (top <= TOP_PX) {
        accumRef.current = { px: 0, el };
        setShown(false);
        return;
      }
      let { px, el: accumEl } = accumRef.current;
      if (accumEl !== el || (px !== 0 && Math.sign(delta) !== Math.sign(px))) {
        px = 0;
        accumEl = el;
      }
      px += delta;
      accumRef.current = { px, el: accumEl };
      if (px >= DIRECTION_PX) {
        setShown(false);
        return;
      }
      if (px <= -DIRECTION_PX) {
        targetRef.current = el;
        setShown(true);
      }
    }

    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    return () => document.removeEventListener("scroll", onScroll, true);
  }, []);

  function scrollUp() {
    const el = targetRef.current ?? document.getElementById("main");
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
  }

  return (
    <div
      inert={shown ? undefined : true}
      className={cn(
        "fixed bottom-6 right-4 z-30 rounded-[8px] shadow-[var(--viewer-shadow-pop)] transition-opacity duration-200 ease-smooth motion-reduce:transition-none sm:right-6",
        shown ? "opacity-100" : "pointer-events-none opacity-0",
      )}
    >
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label="Back to top"
        onClick={scrollUp}
      >
        <ArrowUp className="h-4 w-4" aria-hidden />
      </Button>
    </div>
  );
}
