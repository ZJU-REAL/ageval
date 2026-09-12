/**
 * Greedy 8-position scatter labeling (cartographic / FastLabels) with
 * expanding rings and ggrepel-style leader lines.
 *
 * Points stay fixed. Labels pick the first collision-free candidate around
 * their point, then a farther ring if the plot is dense. A leader is drawn
 * only when the label sits far enough from the point.
 */

export type Rect = { x: number; y: number; w: number; h: number };

export type ScatterLabelInput = {
  x: number;
  y: number;
  text: string;
};

export type LeaderLine = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  ax: number;
  ay: number;
  bx: number;
  by: number;
  cx: number;
  cy: number;
};

export type PlacedScatterLabel = {
  text: string;
  box: Rect;
  tx: number;
  ty: number;
  textAnchor: "start" | "middle" | "end";
  leader: LeaderLine | null;
};

export type ScatterLabelBounds = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};

const FONT_PX = 11;
const LABEL_H = 14;
const MAX_LABEL_W = 144;
const BOX_GAP = 4;
const POINT_R = 4;
const POINT_CLEAR = 8;
const MIN_LEADER = 26;
const ARROW = 6;
const LINE_END_PAD = 12;
const NEIGHBOR_R = 56;

const COMPASS = [
  { dx: 0, dy: 1, anchor: "middle" },
  { dx: 1, dy: 1, anchor: "start" },
  { dx: -1, dy: 1, anchor: "end" },
  { dx: 1, dy: 0, anchor: "start" },
  { dx: -1, dy: 0, anchor: "end" },
  { dx: 0, dy: -1, anchor: "middle" },
  { dx: 1, dy: -1, anchor: "start" },
  { dx: -1, dy: -1, anchor: "end" },
] as const;

const RINGS = [10, 22, 36, 54, 76, 102, 132];

let measureCtx: CanvasRenderingContext2D | null | undefined;

function estimateWidth(text: string): number {
  let w = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    if (code > 0x2e80) w += FONT_PX;
    else if (ch === " " || ch === "." || ch === "/" || ch === "-" || ch === "_") {
      w += 3.6;
    } else if (ch >= "A" && ch <= "Z") w += 7.1;
    else w += 6.3;
  }
  return w;
}

function measureWidth(text: string): number {
  if (typeof document !== "undefined") {
    if (measureCtx === undefined) {
      measureCtx = document.createElement("canvas").getContext("2d");
    }
    if (measureCtx) {
      measureCtx.font = `${FONT_PX}px Geist, Inter, system-ui, sans-serif`;
      return measureCtx.measureText(text).width;
    }
  }
  return estimateWidth(text);
}

function truncateToWidth(text: string, maxW: number): string {
  if (measureWidth(text) <= maxW) return text;
  const ellipsis = "…";
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (measureWidth(text.slice(0, mid) + ellipsis) <= maxW) lo = mid;
    else hi = mid - 1;
  }
  return lo <= 0 ? ellipsis : text.slice(0, lo) + ellipsis;
}

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

function hypot2(dx: number, dy: number): number {
  return dx * dx + dy * dy;
}

function boxFor(
  cx: number,
  cy: number,
  w: number,
  h: number,
  dx: number,
  dy: number,
  pad: number,
): Rect {
  const ox = dx === 0 || dy === 0 ? pad : pad * 0.78;
  const oy = ox;
  let x: number;
  let y: number;
  if (dx === 0) x = cx - w / 2;
  else if (dx > 0) x = cx + ox;
  else x = cx - ox - w;
  if (dy === 0) y = cy - h / 2;
  else if (dy > 0) y = cy + oy;
  else y = cy - oy - h;
  return { x, y, w, h };
}

function clampBox(box: Rect, bounds: ScatterLabelBounds): Rect {
  const w = Math.min(box.w, Math.max(8, bounds.right - bounds.left));
  const h = Math.min(box.h, Math.max(8, bounds.bottom - bounds.top));
  return {
    x: clamp(box.x, bounds.left, bounds.right - w),
    y: clamp(box.y, bounds.top, bounds.bottom - h),
    w,
    h,
  };
}

function overlapArea(a: Rect, b: Rect): number {
  const x0 = Math.max(a.x, b.x);
  const y0 = Math.max(a.y, b.y);
  const x1 = Math.min(a.x + a.w, b.x + b.w);
  const y1 = Math.min(a.y + a.h, b.y + b.h);
  return Math.max(0, x1 - x0) * Math.max(0, y1 - y0);
}

function gapToPoint(px: number, py: number, box: Rect): number {
  const q = closestOnRect(px, py, box);
  return Math.hypot(px - q.x, py - q.y);
}

function boxesOverlap(a: Rect, b: Rect, pad = BOX_GAP): boolean {
  return !(
    a.x + a.w + pad <= b.x ||
    b.x + b.w + pad <= a.x ||
    a.y + a.h + pad <= b.y ||
    b.y + b.h + pad <= a.y
  );
}

function closestOnRect(px: number, py: number, box: Rect): { x: number; y: number } {
  return {
    x: clamp(px, box.x, box.x + box.w),
    y: clamp(py, box.y, box.y + box.h),
  };
}

function circleHitsBox(cx: number, cy: number, r: number, box: Rect): boolean {
  const q = closestOnRect(cx, cy, box);
  return hypot2(cx - q.x, cy - q.y) < r * r;
}

function distPointToSeg(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const vx = x2 - x1;
  const vy = y2 - y1;
  const l2 = hypot2(vx, vy);
  if (l2 === 0) return Math.hypot(px - x1, py - y1);
  const t = clamp(((px - x1) * vx + (py - y1) * vy) / l2, 0, 1);
  return Math.hypot(px - (x1 + t * vx), py - (y1 + t * vy));
}

function segmentsCross(
  a: { x1: number; y1: number; x2: number; y2: number },
  b: { x1: number; y1: number; x2: number; y2: number },
): boolean {
  const dax = a.x2 - a.x1;
  const day = a.y2 - a.y1;
  const dbx = b.x2 - b.x1;
  const dby = b.y2 - b.y1;
  const den = dax * dby - day * dbx;
  if (Math.abs(den) < 1e-6) return false;
  const t = ((b.x1 - a.x1) * dby - (b.y1 - a.y1) * dbx) / den;
  const u = ((b.x1 - a.x1) * day - (b.y1 - a.y1) * dax) / den;
  return t > 0.04 && t < 0.96 && u > 0.04 && u < 0.96;
}

function leaderGeometry(
  px: number,
  py: number,
  box: Rect,
  others: { x: number; y: number }[],
  selfIndex: number,
): LeaderLine | null {
  const q = closestOnRect(px, py, box);
  const dx = px - q.x;
  const dy = py - q.y;
  const len = Math.hypot(dx, dy);
  if (len < MIN_LEADER) return null;
  const ux = dx / len;
  const uy = dy / len;
  const endTrim = LINE_END_PAD + ARROW * 0.35;
  if (len <= endTrim + 4) return null;
  const x1 = q.x;
  const y1 = q.y;
  const tipX = px - ux * LINE_END_PAD;
  const tipY = py - uy * LINE_END_PAD;
  const x2 = tipX - ux * ARROW;
  const y2 = tipY - uy * ARROW;
  const pxn = -uy;
  const pyn = ux;
  const half = ARROW * 0.42;
  const line = { x1, y1, x2: tipX, y2: tipY };
  for (let i = 0; i < others.length; i++) {
    if (i === selfIndex) continue;
    if (distPointToSeg(others[i].x, others[i].y, line.x1, line.y1, line.x2, line.y2) < POINT_CLEAR) {
      return null;
    }
  }
  return {
    x1,
    y1,
    x2,
    y2,
    ax: tipX,
    ay: tipY,
    bx: x2 + pxn * half,
    by: y2 + pyn * half,
    cx: x2 - pxn * half,
    cy: y2 - pyn * half,
  };
}

function textPos(
  box: Rect,
  anchor: "start" | "middle" | "end",
): { tx: number; ty: number } {
  const tx =
    anchor === "start" ? box.x : anchor === "end" ? box.x + box.w : box.x + box.w / 2;
  return { tx, ty: box.y + box.h * 0.78 };
}

function candidateScore(opts: {
  ring: number;
  dir: number;
  box: Rect;
  raw: Rect;
  leader: LeaderLine | null;
  gap: number;
  placed: PlacedScatterLabel[];
  points: { x: number; y: number }[];
  self: number;
  obstacles: Rect[];
}): number {
  const { ring, dir, box, raw, leader, gap, placed, points, self, obstacles } = opts;
  let score = ring * 10 + dir;
  const shift = Math.abs(box.x - raw.x) + Math.abs(box.y - raw.y);
  score += shift * 0.15;
  if (gap >= MIN_LEADER) {
    score += leader ? 6 : 2500;
  } else {
    score -= 4;
  }
  for (const other of placed) {
    const area = overlapArea(box, other.box);
    if (area > 0) score += 4000 + area;
    if (leader && other.leader && segmentsCross(leader, other.leader)) score += 55;
    if (leader && distPointToSeg(other.tx, other.ty, leader.x1, leader.y1, leader.x2, leader.y2) < 8) {
      score += 40;
    }
  }
  for (let i = 0; i < points.length; i++) {
    if (i === self) continue;
    if (circleHitsBox(points[i].x, points[i].y, POINT_CLEAR, box)) score += 900;
  }
  if (circleHitsBox(points[self].x, points[self].y, POINT_R + 1, box)) score += 1200;
  for (const obs of obstacles) {
    const area = overlapArea(box, obs);
    if (area > 0) score += 200 + area;
  }
  return score;
}

export function placeScatterLabels(
  items: readonly ScatterLabelInput[],
  bounds: ScatterLabelBounds,
  obstacles: readonly Rect[] = [],
): PlacedScatterLabel[] {
  const prepared = items.map((item, index) => {
    const text = truncateToWidth(item.text, MAX_LABEL_W);
    const w = Math.min(MAX_LABEL_W, Math.max(8, Math.ceil(measureWidth(text) + 2)));
    return { index, x: item.x, y: item.y, text, w, h: LABEL_H };
  });
  const neighborCounts = prepared.map((a) =>
    prepared.reduce((n, b) => {
      if (a.index === b.index) return n;
      return hypot2(a.x - b.x, a.y - b.y) < NEIGHBOR_R * NEIGHBOR_R ? n + 1 : n;
    }, 0),
  );
  const order = prepared
    .map((_, i) => i)
    .sort((ia, ib) => {
      const da = neighborCounts[ia] - neighborCounts[ib];
      if (da !== 0) return -da;
      const wa = prepared[ia].w - prepared[ib].w;
      if (wa !== 0) return -wa;
      return prepared[ia].x - prepared[ib].x || prepared[ia].y - prepared[ib].y;
    });

  const placedByIndex: Array<PlacedScatterLabel | undefined> = Array.from({
    length: items.length,
  });
  const points = prepared.map((p) => ({ x: p.x, y: p.y }));
  const obstacleList = [...obstacles];

  for (const idx of order) {
    const item = prepared[idx];
    const placed = placedByIndex.filter((p): p is PlacedScatterLabel => p != null);
    let best: { score: number; label: PlacedScatterLabel } | null = null;
    for (let ring = 0; ring < RINGS.length; ring++) {
      const pad = RINGS[ring];
      for (let dir = 0; dir < COMPASS.length; dir++) {
        const { dx, dy, anchor } = COMPASS[dir];
        const raw = boxFor(item.x, item.y, item.w, item.h, dx, dy, pad);
        const box = clampBox(raw, bounds);
        if (placed.some((p) => boxesOverlap(box, p.box))) continue;
        if (circleHitsBox(item.x, item.y, POINT_R + 1, box)) continue;
        let hitsOther = false;
        for (let i = 0; i < points.length; i++) {
          if (i === idx) continue;
          if (circleHitsBox(points[i].x, points[i].y, POINT_CLEAR, box)) {
            hitsOther = true;
            break;
          }
        }
        if (hitsOther) continue;
        const gap = gapToPoint(item.x, item.y, box);
        const leader = leaderGeometry(item.x, item.y, box, points, idx);
        if (gap >= MIN_LEADER && !leader) continue;
        const score = candidateScore({
          ring,
          dir,
          box,
          raw,
          leader,
          gap,
          placed,
          points,
          self: idx,
          obstacles: obstacleList,
        });
        if (!best || score < best.score) {
          const { tx, ty } = textPos(box, anchor);
          best = {
            score,
            label: { text: item.text, box, tx, ty, textAnchor: anchor, leader },
          };
        }
      }
      if (best && best.score < 50) break;
    }
    if (!best) {
      let fallback: { score: number; label: PlacedScatterLabel } | null = null;
      for (let ring = 0; ring < RINGS.length; ring++) {
        const pad = RINGS[ring];
        for (let dir = 0; dir < COMPASS.length; dir++) {
          const { dx, dy, anchor } = COMPASS[dir];
          const raw = boxFor(item.x, item.y, item.w, item.h, dx, dy, pad);
          const box = clampBox(raw, bounds);
          const gap = gapToPoint(item.x, item.y, box);
          const leader = leaderGeometry(item.x, item.y, box, points, idx);
          const score = candidateScore({
            ring,
            dir,
            box,
            raw,
            leader,
            gap,
            placed,
            points,
            self: idx,
            obstacles: obstacleList,
          });
          if (!fallback || score < fallback.score) {
            const { tx, ty } = textPos(box, anchor);
            fallback = {
              score,
              label: { text: item.text, box, tx, ty, textAnchor: anchor, leader },
            };
          }
        }
      }
      best = fallback;
    }
    placedByIndex[idx] =
      best?.label ??
      (() => {
        const box = clampBox(
          boxFor(item.x, item.y, item.w, item.h, 0, 1, RINGS[0]),
          bounds,
        );
        const { tx, ty } = textPos(box, "middle");
        return {
          text: item.text,
          box,
          tx,
          ty,
          textAnchor: "middle" as const,
          leader: leaderGeometry(item.x, item.y, box, points, idx),
        };
      })();
  }

  return placedByIndex.map((p, i) => {
    if (p) return p;
    const item = prepared[i];
    const box = clampBox(boxFor(item.x, item.y, item.w, item.h, 0, 1, RINGS[0]), bounds);
    const { tx, ty } = textPos(box, "middle");
    return {
      text: item.text,
      box,
      tx,
      ty,
      textAnchor: "middle",
      leader: leaderGeometry(item.x, item.y, box, points, i),
    };
  });
}
