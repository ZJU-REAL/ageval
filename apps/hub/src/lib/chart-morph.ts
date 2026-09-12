/**
 * Identity-preserving scatter morph (Heer & Robertson / d3-transition /
 * Recharts interpolate). CSS Motion libraries stay out of Hub; this is rAF
 * + the product ease-smooth curve. Reduced motion jumps.
 */
import { useLayoutEffect, useRef, useState } from "react";

import type { LeaderLine } from "@/lib/scatter-label-layout";

export const MORPH_MS = 500;

export type ScatterPose = {
  id: string;
  colorIndex: number;
  cx: number;
  cy: number;
  tx: number;
  ty: number;
  textAnchor: "start" | "middle" | "end";
  text: string;
  leader: LeaderLine | null;
  onFront: boolean;
  opacity: number;
};

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** CSS cubic-bezier(0.22, 1, 0.36, 1) — --ease-smooth. */
function easeSmooth(t: number): number {
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  const x1 = 0.22;
  const y1 = 1;
  const x2 = 0.36;
  const y2 = 1;
  let x = t;
  for (let i = 0; i < 6; i++) {
    const u = 1 - x;
    const sx = 3 * u * u * x * x1 + 3 * u * x * x * x2 + x * x * x;
    const dx = 3 * u * u * x1 + 6 * u * x * (x2 - x1) + 3 * x * x * (1 - x2);
    if (Math.abs(dx) < 1e-6) break;
    x -= (sx - t) / dx;
  }
  const u = 1 - x;
  return 3 * u * u * x * y1 + 3 * u * x * x * y2 + x * x * x;
}

function lerpLeader(
  a: LeaderLine | null,
  b: LeaderLine | null,
  t: number,
): LeaderLine | null {
  if (a && b) {
    return {
      x1: lerp(a.x1, b.x1, t),
      y1: lerp(a.y1, b.y1, t),
      x2: lerp(a.x2, b.x2, t),
      y2: lerp(a.y2, b.y2, t),
      ax: lerp(a.ax, b.ax, t),
      ay: lerp(a.ay, b.ay, t),
      bx: lerp(a.bx, b.bx, t),
      by: lerp(a.by, b.by, t),
      cx: lerp(a.cx, b.cx, t),
      cy: lerp(a.cy, b.cy, t),
    };
  }
  if (b) return t > 0.65 ? b : null;
  if (a) return t < 0.35 ? a : null;
  return null;
}

export function mixScatterPoses(
  from: ScatterPose[],
  to: ScatterPose[],
  t: number,
): ScatterPose[] {
  const fromM = new Map(from.map((p) => [p.id, p]));
  const toM = new Map(to.map((p) => [p.id, p]));
  const ids = new Set([...fromM.keys(), ...toM.keys()]);
  const out: ScatterPose[] = [];
  for (const id of ids) {
    const a = fromM.get(id);
    const b = toM.get(id);
    if (a && b) {
      out.push({
        ...b,
        cx: lerp(a.cx, b.cx, t),
        cy: lerp(a.cy, b.cy, t),
        tx: lerp(a.tx, b.tx, t),
        ty: lerp(a.ty, b.ty, t),
        leader: lerpLeader(a.leader, b.leader, t),
        onFront: t >= 0.45 ? b.onFront : a.onFront,
        opacity: 1,
      });
    } else if (b) {
      out.push({ ...b, opacity: t });
    } else if (a) {
      out.push({ ...a, opacity: 1 - t });
    }
  }
  return out;
}

export function useScatterMorph(
  target: ScatterPose[],
  trigger: string,
): ScatterPose[] {
  const triggerRef = useRef(trigger);
  const shownRef = useRef(target);
  const [shown, setShown] = useState(target);

  useLayoutEffect(() => {
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const switched = triggerRef.current !== trigger;
    triggerRef.current = trigger;
    if (!switched || shownRef.current.length === 0 || reduced || target.length === 0) {
      shownRef.current = target;
      setShown(target);
      return;
    }
    const from = shownRef.current;
    const t0 = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const u = Math.min(1, (now - t0) / MORPH_MS);
      const mixed = mixScatterPoses(from, target, easeSmooth(u));
      shownRef.current = mixed;
      setShown(mixed);
      if (u < 1) raf = requestAnimationFrame(tick);
      else {
        shownRef.current = target;
        setShown(target);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, trigger]);

  return shown;
}
