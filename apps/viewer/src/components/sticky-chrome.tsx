import { useLayoutEffect, useRef, type ReactNode } from "react";

/** Search and filters stick to the top of the scrolling main column. */
export function StickyChrome({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const chrome = ref.current;
    const scroller = document.getElementById("main");
    if (!chrome || !scroller) return;
    const apply = () => {
      scroller.style.setProperty("--viewer-stick-top", `${chrome.offsetHeight}px`);
    };
    const ro = new ResizeObserver(apply);
    ro.observe(chrome);
    window.addEventListener("resize", apply);
    apply();
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", apply);
      scroller.style.removeProperty("--viewer-stick-top");
    };
  }, []);

  return (
    <div
      ref={ref}
      className="relative sticky top-0 z-20 -mx-4 -mt-5 mb-4 flex flex-col gap-2 bg-canvas px-4 pb-3 pt-0 sm:-mx-6 sm:px-6"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-full h-5 bg-canvas"
      />
      {children}
    </div>
  );
}

/** Column labels sit under the sticky search bar. */
export const STICKY_HEAD =
  "[&_th]:sticky [&_th]:top-[var(--viewer-stick-top,0px)] [&_th]:z-10 [&_th]:bg-canvas-soft";

/** Column labels sit under a pinned organization heading. */
export const STICKY_HEAD_UNDER_GROUP =
  "[&_th]:sticky [&_th]:top-[calc(var(--viewer-stick-top,0px)+2.25rem)] [&_th]:z-10 [&_th]:bg-canvas-soft";
