import { useEffect, useRef, useState, type RefObject } from "react";

/** Working-form thinking mark: owl face as a thread wound into a knot. */

interface ModeOpts {
  [key: string]: number | undefined;
}
interface LogoPointSet {
  readonly n: number;
  readonly p: Float32Array;
  readonly e: Float32Array;
}
type SeatMap = Uint32Array;
interface LogoBinding {
  readonly points: LogoPointSet;
  readonly seats: SeatMap;
}

interface Dot {
  x: number;
  y: number;
  z: number;
  r: number;
  white: number;
  a?: number;
}

interface Line {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  white: number;
  a?: number;
  w: number;
}

interface OrbFrame {
  dots: Dot[];
  lines: Line[];
}

type Projector = (x: number, y: number, z: number) => [number, number, number];

function fibDir(i: number, n: number): [number, number, number] {
  const golden = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - (2 * (i + 0.5)) / n;
  const rad = Math.sqrt(1 - y * y);
  const a = i * golden;
  return [rad * Math.cos(a), y, rad * Math.sin(a)];
}

function makeProj(
  yaw: number,
  tilt: number,
  cx: number,
  cy: number,
  scale: number,
): Projector {
  const st = Math.sin(tilt);
  const ct = Math.cos(tilt);
  const sy = Math.sin(yaw);
  const cyw = Math.cos(yaw);
  return (x, y, z) => {
    const x1 = x * cyw + z * sy;
    const z1 = -x * sy + z * cyw;
    const y1 = y * ct - z1 * st;
    const z2 = y * st + z1 * ct;
    return [cx + x1 * scale, cy - y1 * scale, z2];
  };
}

function paint(ctx: CanvasRenderingContext2D, dots: Dot[], dark: boolean): void {
  for (const d of dots) {
    const alpha = d.a ?? 1;
    const w = Math.min(1, Math.max(0, d.white));
    const g = Math.round((dark ? 1 - w : w) * 255);
    ctx.fillStyle = `rgba(${g},${g},${g},${alpha})`;
    ctx.beginPath();
    ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
    ctx.fill();
  }
}

function paintLines(
  ctx: CanvasRenderingContext2D,
  lines: Line[],
  dark: boolean,
): void {
  for (const l of lines) {
    const alpha = l.a ?? 1;
    const w = Math.min(1, Math.max(0, l.white));
    const g = Math.round((dark ? 1 - w : w) * 255);
    ctx.strokeStyle = `rgba(${g},${g},${g},${alpha})`;
    ctx.lineWidth = l.w;
    ctx.beginPath();
    ctx.moveTo(l.x1, l.y1);
    ctx.lineTo(l.x2, l.y2);
    ctx.stroke();
  }
}

function finalizeFrame(dots: Dot[], lines: Line[], rMin = 0.3): OrbFrame {
  const visible: Dot[] = [];
  for (const d of dots) {
    if ((d.a ?? 1) < 0.02) continue;
    d.r = Math.max(rMin, d.r);
    visible.push(d);
  }
  visible.sort((a, b) => a.z - b.z);
  return { dots: visible, lines: lines.filter((l) => (l.a ?? 1) >= 0.02) };
}

function paintFrame(
  ctx: CanvasRenderingContext2D,
  frame: OrbFrame,
  dark: boolean,
): void {
  if (frame.lines.length) paintLines(ctx, frame.lines, dark);
  paint(ctx, frame.dots, dark);
}

function radiusScale(size: number, pow: number): number {
  return (size / 300) ** pow;
}

const TURN = Math.PI * 2;

function clamp01(x: number): number {
  return x < 0 ? 0 : x > 1 ? 1 : x;
}

function empty(): OrbFrame {
  return { dots: [], lines: [] };
}

function inkOf(
  o: Record<string, number | undefined>,
  zx: number,
  edge: number,
): number {
  const far = o.inkFar ?? 0.6;
  const span = o.inkSpan ?? 0.5;
  const rim = o.inkRim ?? 0.16;
  return far - span * zx - rim * (1 - edge);
}

function expoInOut(x: number): number {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  return x < 0.5 ? 2 ** (20 * x - 10) / 2 : (2 - 2 ** (-20 * x + 10)) / 2;
}

function morphEase(x: number, expo: number): number {
  const smooth = x * x * x * (x * (x * 6 - 15) + 10);
  return smooth + (expoInOut(x) - smooth) * expo;
}

function cruise(x: number, edge: number): number {
  const a = Math.min(0.49, Math.max(0.001, edge));
  const v = 1 / (1 - a);
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  if (x < a) {
    const u = x / a;
    return v * a * (u * u * u - (u * u * u * u) / 2);
  }
  if (x > 1 - a) {
    const u = (1 - x) / a;
    return 1 - v * a * (u * u * u - (u * u * u * u) / 2);
  }
  return v * (a * 0.5 + (x - a));
}

interface Beat {
  m: number;
  turns: number;
  workT: number;
  local: number;
  cycle: number;
}

function beatAt(
  t: number,
  dwell: number,
  morph: number,
  turns: number,
  settle: number,
  expo = 0.3,
): Beat {
  const cycle = dwell + morph * 2;
  const local = t % cycle;
  const spinSpan = dwell + morph * settle;
  const spun = turns * cruise(Math.min(1, local / spinSpan), 0.22);

  if (local < dwell) return { m: 0, turns: spun, workT: local, local, cycle };
  const intoMorph = local - dwell;
  if (intoMorph < morph) {
    return {
      m: morphEase(intoMorph / morph, expo),
      turns: spun,
      workT: -1,
      local,
      cycle,
    };
  }
  return {
    m: morphEase(1 - (intoMorph - morph) / morph, expo),
    turns: spun,
    workT: -1,
    local,
    cycle,
  };
}

function frameLogoWork(
  size: number,
  t: number,
  o: ModeOpts,
  logo?: LogoBinding,
): OrbFrame {
  if (!logo) return empty();
  const { p, e, n } = logo.points;
  const seats = logo.seats;
  const cx = size / 2;
  const R = (size / 2) * 0.82;
  const rs = radiusScale(size, o.rsPow ?? 0.6);

  const dwell = o.dwell ?? 5.5;
  const morph = o.morph ?? 1.9;
  const b = beatAt(t, dwell, morph, o.turns ?? 0, o.settle ?? 0.1, o.expo ?? 0.3);
  const m = b.m;
  const c = 1 - m;

  const pt = makeProj(
    (o.lean ?? 0.4) + (o.yawAmp ?? 0.3) * Math.sin(t * (o.yawRate ?? 0.26)) * c,
    (o.tilt ?? 0.4) * c,
    cx,
    cx,
    R,
  );

  const into = b.local - dwell;
  const prog =
    b.local < dwell
      ? b.local / dwell
      : into < morph
        ? 1
        : clamp01(1 - (into - morph) / morph);
  const head = prog * n;
  const feather = Math.max(1, n * (o.feather ?? 0.02));
  const headW = Math.max(1, n * (o.headWidth ?? 0.01));
  const winding = b.local < dwell;

  const wraps = o.wraps ?? 3;
  const turns = o.knotTurns ?? 2;
  const major = o.major ?? 0.62;
  const minor = o.minor ?? 0.3;
  const spin = t * (o.spin ?? 0.24);

  const dots: Dot[] = [];
  for (let i = 0; i < n; i++) {
    const seat = seats[i];
    const u = (seat / n) * TURN;
    const ring = major + minor * Math.cos(turns * u);
    const kx = ring * Math.cos(wraps * u);
    const ky = minor * Math.sin(turns * u);
    const kz = ring * Math.sin(wraps * u);

    const ca = Math.cos(spin);
    const sa = Math.sin(spin);
    const bx = kx * ca + kz * sa;
    const bz = -kx * sa + kz * ca;

    const lx = p[i * 3];
    const ly = p[i * 3 + 1];
    const lz = p[i * 3 + 2];
    const x = lx + (bx - lx) * c;
    const y = ly + (ky - ly) * c;
    const z3 = lz + (bz - lz) * c;

    const laid = clamp01((head - seat) / feather);
    const at = winding ? Math.exp(-(((seat - head) / headW) ** 2)) : 0;

    const [px, py, z] = pt(x, y, z3);
    const zx = clamp01((z + 1) / 2);
    dots.push({
      x: px,
      y: py,
      z,
      r: ((o.rBase ?? 0.55) + (o.rDepth ?? 1.4) * zx + (o.headR ?? 1.2) * at * c) * rs,
      white: inkOf(o, zx, e[i] * m + (1 - m)) - (o.headInk ?? 0.4) * at * c,
      a: 1 - (1 - laid) * c,
    });
  }
  return finalizeFrame(dots, [], o.rMin);
}

const POINTS: LogoPointSet = {
  n: 289,
  p: Float32Array.from([-0.621,0.762,0.105,-0.588,0.714,0.148,-0.536,0.657,0.174,-0.629,0.722,0,-0.59,0.672,0.105,-0.553,0.695,0.139,-0.487,0.636,0.139,-0.466,0.566,0,-0.503,0.597,0.091,0.613,0.762,0.091,0.556,0.72,0.091,0.542,0.669,0.174,0.608,0.7,0.091,0.489,0.66,0.105,0.475,0.622,0.148,0.523,0.629,0.105,0.582,0.668,0,-0.699,0.621,0.091,-0.67,0.584,0.148,-0.641,0.556,0.148,-0.705,0.513,0.252,-0.66,0.513,0.223,-0.767,0.479,0.148,-0.741,0.543,0.129,-0.7,0.472,0.203,-0.719,0.414,0.252,-0.726,0.583,0.091,-0.585,0.525,0.105,-0.541,0.488,0,-0.773,0.412,0.091,-0.671,0.442,0.091,-0.611,0.485,0.21,-0.568,0.42,0.105,-0.704,0.344,0.246,-0.679,0.288,0.235,-0.67,0.37,0.157,-0.616,0.443,0.091,-0.51,0.402,0.174,-0.649,0.334,0.105,-0.533,0.449,0.174,-0.724,0.306,0.139,-0.748,0.368,0.148,-0.699,0.24,0.139,-0.635,0.262,0.174,-0.634,0.22,0.229,-0.657,0.188,0.129,-0.627,0.142,0.091,-0.614,0.186,0.21,-0.594,0.241,0.091,-0.566,0.193,0.105,-0.58,0.139,0.203,-0.482,0.432,0.091,-0.515,0.146,0.091,-0.457,0.368,0.182,-0.553,0.099,0.148,-0.49,0.11,0.174,-0.524,0.037,0.174,-0.474,0.013,0.235,-0.444,0.066,0.246,-0.408,0.341,0.105,-0.412,0.027,0.129,-0.493,0.064,0.257,-0.432,0.105,0.129,-0.409,0.3,0.105,-0.449,0.322,0.091,-0.527,-0.03,0.105,-0.361,0.298,0.091,-0.486,-0.027,0.229,-0.376,0.075,0.129,-0.465,-0.07,0.21,-0.344,0.051,0.148,-0.348,0.247,0.105,-0.44,-0.02,0.129,-0.402,-0.077,0.105,-0.504,-0.075,0.091,-0.443,-0.108,0.148,-0.294,0.03,0.139,-0.281,0.207,0.091,-0.319,-0.005,0.105,-0.375,-0.116,0.182,-0.33,-0.106,0.139,-0.371,0.015,0.129,-0.262,0.172,0.105,-0.309,0.245,0.105,-0.271,-0.015,0.148,-0.219,0.133,0.105,-0.413,-0.134,0.091,-0.287,-0.118,0.105,-0.198,0.096,0.091,-0.225,-0.027,0.139,-0.199,-0.082,0.105,-0.148,0.069,0.105,-0.103,0.038,0.182,-0.071,0.073,0.091,-0.079,-0.012,0.189,-0.06,-0.07,0.174,0.001,-0.045,0.31,0.05,-0.075,0.196,-0.05,0.02,0.257,-0.04,-0.032,0.262,-0.011,0.001,0.323,0.021,0.031,0.257,-0.014,-0.113,0.235,0.075,-0.004,0.203,-0.044,-0.142,0.105,0.042,-0.032,0.257,-0.072,-0.108,0.091,0.021,-0.133,0.182,0.088,-0.044,0.105,0.004,-0.196,0.091,-0.02,0.05,0.229,0.088,0.034,0.21,-0.004,0.095,0.148,0.114,-0.001,0.091,0.13,0.066,0.091,0.044,0.066,0.166,0.169,0.079,0.091,0.195,0.124,0.091,0.237,0.169,0.091,0.271,0.214,0.091,0.312,0.226,0.129,0.329,0.263,0.105,0.364,0.311,0.105,0.386,0.278,0.105,0.4,0.337,0.139,0.445,0.393,0.139,0.502,0.362,0,0.442,0.348,0.174,0.5,0.423,0.182,0.55,0.416,0.139,0.536,0.478,0.148,0.591,0.524,0.148,0.598,0.454,0.129,0.641,0.501,0.174,0.688,0.536,0.252,0.708,0.576,0.139,0.67,0.455,0.091,0.726,0.503,0.21,0.648,0.549,0.203,0.662,0.589,0.139,0.575,0.485,0.203,0.722,0.441,0.252,0.684,0.496,0.148,0.66,0.384,0.091,0.707,0.372,0.246,0.766,0.453,0.129,0.689,0.415,0.182,0.755,0.403,0.139,0.768,0.496,0.091,0.729,0.336,0.139,0.68,0.339,0.229,0.682,0.282,0.148,0.748,0.54,0.091,0.625,0.317,0.091,0.621,0.254,0.182,0.662,0.236,0.105,0.628,0.198,0.166,0.597,0.221,0.166,0.605,0.14,0.148,0.561,0.206,0.105,0.571,0.163,0.203,0.55,0.129,0.21,0.58,0.089,0.139,0.54,0.069,0.21,0.511,0.119,0.182,0.521,0.157,0.105,0.481,0.023,0.257,0.462,0.109,0.139,0.424,0.045,0.216,0.519,-0.004,0.148,0.494,0.08,0.252,0.551,0.031,0.105,0.422,0.09,0.148,0.442,0.006,0.189,0.48,-0.039,0.182,0.372,0.029,0.157,0.47,-0.089,0.091,0.426,-0.033,0.129,0.382,0.09,0.129,0.417,-0.108,0.129,0.309,0.062,0.091,0.283,0.03,0.139,0.371,-0.109,0.166,0.324,-0.12,0.129,0.311,-0.016,0.091,0.333,0.018,0.157,0.238,0.015,0.091,0.254,-0.021,0.166,0.214,-0.021,0.091,0.19,-0.052,0.091,0.4,-0.063,0.091,0.175,-0.089,0,0.691,0.621,0.091,-0.449,0.605,0,0.441,0.59,0.129,-0.574,0.465,0.21,0.816,0.355,0.091,0.843,0.298,0.091,0.85,0.234,0.129,-0.84,0.324,0.091,-0.855,0.277,0.105,-0.86,0.23,0.129,-0.875,0.191,0.091,-0.871,0.147,0.129,-0.882,0.082,0.091,-0.861,0.013,0.157,-0.844,0.048,0.129,-0.818,-0.051,0.166,-0.786,-0.076,0.105,-0.778,-0.121,0.174,-0.817,-0.005,0.105,-0.868,-0.029,0.091,-0.821,-0.142,0.091,-0.791,-0.179,0.105,-0.843,-0.086,0.091,-0.751,-0.155,0.148,-0.757,-0.197,0.166,-0.714,-0.181,0.091,-0.705,-0.227,0.182,-0.675,-0.274,0.174,-0.633,-0.3,0.182,-0.656,-0.235,0.091,-0.584,-0.336,0.148,-0.526,-0.346,0.174,-0.557,-0.303,0.091,-0.481,-0.367,0.157,-0.603,-0.273,0.091,-0.431,-0.374,0.157,-0.375,-0.357,0.091,-0.348,-0.39,0.091,-0.314,-0.355,0,-0.237,-0.363,0.091,0.848,0.184,0.129,0.858,0.143,0.139,0.875,0.093,0.091,0.835,0.084,0.091,0.856,0.039,0.129,0.838,-0.024,0.157,0.788,-0.074,0.139,0.763,-0.134,0.174,0.738,-0.178,0.196,0.845,-0.063,0.091,0.789,-0.17,0.105,0.811,-0.115,0.129,0.808,0.003,0,0.684,-0.202,0.105,0.754,-0.213,0.105,0.797,-0.035,0.105,0.71,-0.244,0.148,0.664,-0.262,0.203,0.635,-0.304,0.148,0.6,-0.282,0.129,0.593,-0.324,0.148,0.523,-0.327,0.129,0.555,-0.35,0.139,0.555,-0.304,0.091,0.501,-0.36,0.166,0.459,-0.359,0.157,0.419,-0.386,0.129,0.36,-0.389,0.091,0.296,-0.372,0.091,-0.84,0.09,0,0.066,-0.113,0,0.27,-0.113,0,0.23,-0.065,0.091,-0.746,-0.238,0.091,-0.715,-0.27,0.091,-0.152,-0.301,0.105,-0.14,-0.345,0.148,-0.119,-0.402,0.129,-0.125,-0.456,0.105,0.145,-0.301,0.091,0.128,-0.336,0.091,0.139,-0.398,0.091,0.099,-0.433,0.129,0.074,-0.499,0,0.12,-0.481,0.091,0.074,-0.541,0.091,0.068,-0.615,0,0.238,-0.348,0.091,-0.387,-0.395,0.091,-0.09,-0.473,0.091,-0.11,-0.519,0.091,-0.066,-0.578,0.091,-0.058,-0.62,0.091,-0.048,-0.668,0.091,-0.032,-0.723,0.091,-0.074,-0.535,0.091,0.035,-0.676,0.091]),
  e: Float32Array.from([0.095,0.19,0.262,0,0.095,0.167,0.167,0,0.071,0.071,0.071,0.262,0.071,0.095,0.19,0.095,0,0.071,0.19,0.19,0.548,0.429,0.19,0.143,0.357,0.548,0.071,0.095,0,0.071,0.071,0.381,0.095,0.524,0.476,0.214,0.071,0.262,0.095,0.262,0.167,0.19,0.167,0.262,0.452,0.143,0.071,0.381,0.071,0.095,0.357,0.071,0.071,0.286,0.19,0.262,0.262,0.476,0.524,0.095,0.143,0.571,0.143,0.095,0.071,0.095,0.071,0.452,0.143,0.381,0.19,0.095,0.143,0.095,0.071,0.19,0.167,0.071,0.095,0.286,0.167,0.143,0.095,0.095,0.19,0.095,0.071,0.095,0.071,0.167,0.095,0.095,0.286,0.071,0.31,0.262,0.833,0.333,0.571,0.595,0.905,0.571,0.476,0.357,0.095,0.571,0.071,0.286,0.095,0.071,0.452,0.381,0.19,0.071,0.071,0.238,0.071,0.071,0.071,0.071,0.143,0.095,0.095,0.095,0.167,0.167,0,0.262,0.286,0.167,0.19,0.19,0.143,0.262,0.548,0.167,0.071,0.381,0.357,0.167,0.357,0.548,0.19,0.071,0.524,0.143,0.286,0.167,0.071,0.167,0.452,0.19,0.071,0.071,0.286,0.095,0.238,0.238,0.19,0.095,0.357,0.381,0.167,0.381,0.286,0.095,0.571,0.167,0.405,0.19,0.548,0.095,0.19,0.31,0.286,0.214,0.071,0.143,0.143,0.143,0.071,0.167,0.238,0.143,0.071,0.214,0.071,0.238,0.071,0.071,0.071,0,0.071,0,0.143,0.381,0.071,0.071,0.143,0.071,0.095,0.143,0.071,0.143,0.071,0.214,0.143,0.238,0.095,0.262,0.095,0.071,0.071,0.095,0.071,0.19,0.238,0.071,0.286,0.262,0.286,0.071,0.19,0.262,0.071,0.214,0.071,0.214,0.071,0.071,0,0.071,0.143,0.167,0.071,0.071,0.143,0.214,0.167,0.262,0.333,0.071,0.095,0.143,0,0.095,0.095,0.095,0.19,0.357,0.19,0.143,0.19,0.143,0.167,0.071,0.238,0.214,0.143,0.071,0.071,0,0,0,0.071,0.071,0.071,0.095,0.19,0.143,0.095,0.071,0.071,0.071,0.143,0,0.071,0.071,0,0.071,0.071,0.071,0.071,0.071,0.071,0.071,0.071,0.071,0.071])
};

const OPTS: ModeOpts = {
  dwell: 3,
  morph: 1.9,
  expo: 0.3,
  settle: 0.1,
  turns: 0,
  lean: 0.4,
  yawAmp: 0.3,
  yawRate: 0.26,
  tilt: 0.4,
  wraps: 3,
  knotTurns: 2,
  major: 0.62,
  minor: 0.3,
  spin: 0.24,
  feather: 0.02,
  headWidth: 0.01,
  headR: 1.2,
  headInk: 0.4,
  rBase: 0.75,
  rDepth: 1.6,
  inkFar: 0.6,
  inkSpan: 0.5,
  inkRim: 0.16,
  rsPow: 0.6,
  rMin: 0.3
};

function seatMap(points: LogoPointSet): SeatMap {
  const n = points.n;
  const byLogo = new Uint32Array(n);
  const bySeat = new Uint32Array(n);
  const logoAng = new Float32Array(n);
  const seatAng = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    byLogo[i] = i;
    bySeat[i] = i;
    logoAng[i] = Math.atan2(points.p[i * 3 + 1], points.p[i * 3]);
    const [sx, sy] = fibDir(i, n);
    seatAng[i] = Math.atan2(sy, sx);
  }
  byLogo.sort((a, b) => logoAng[a] - logoAng[b]);
  bySeat.sort((a, b) => seatAng[a] - seatAng[b]);
  const seats = new Uint32Array(n);
  for (let k = 0; k < n; k++) seats[byLogo[k]] = bySeat[k];
  return seats;
}

const BINDING: LogoBinding = { points: POINTS, seats: seatMap(POINTS) };

function useDark(host: RefObject<Element | null>): boolean {
  const [dark, setDark] = useState(true);
  useEffect(() => {
    const resolve = () => {
      let node: Element | null = host.current;
      while (node) {
        const attr = node.getAttribute("data-theme");
        if (attr === "dark") return setDark(true);
        if (attr === "light") return setDark(false);
        if (node.classList.contains("dark")) return setDark(true);
        if (node.classList.contains("light")) return setDark(false);
        node = node.parentElement;
      }
      setDark(matchMedia("(prefers-color-scheme: dark)").matches);
    };
    resolve();
    const mq = matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", resolve);
    const mo = new MutationObserver(resolve);
    mo.observe(document.documentElement, { attributes: true, subtree: true });
    return () => {
      mq.removeEventListener("change", resolve);
      mo.disconnect();
    };
  }, [host]);
  return dark;
}

export function ThinkingLogo({ size = 96 }: { size?: number }) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const dark = useDark(ref);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = Math.min(2, devicePixelRatio || 1);
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const render = (t: number) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);
      const frame = frameLogoWork(size, t, OPTS, BINDING);
      paintFrame(ctx, frame, dark);
    };

    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      render(4.2);
      return;
    }

    let raf = 0;
    let running = false;
    const loop = () => {
      render(performance.now() / 1000);
      if (running) raf = requestAnimationFrame(loop);
    };
    const start = () => {
      if (running) return;
      running = true;
      raf = requestAnimationFrame(loop);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };

    render(performance.now() / 1000);

    let visible = true;
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible && document.visibilityState !== "hidden") start();
      else stop();
    });
    io.observe(canvas);
    const onVis = () => {
      if (document.visibilityState === "hidden") stop();
      else if (visible) start();
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      stop();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [size, dark]);

  return (
    <canvas
      ref={ref}
      role="img"
      aria-hidden
      style={{ width: size, height: size, display: "block" }}
    />
  );
}
