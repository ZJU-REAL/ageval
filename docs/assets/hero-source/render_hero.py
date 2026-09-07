#!/usr/bin/env python3
"""ageval README hero + GitHub Social preview.

README posters: 1680×600, EN + ZH.
GitHub Social preview: 1280×640, EN only (Settings → Social preview).

Centered Geist title, compact pact strip, quiet logo marquee.
Pixel-owl wash is a 52×52 digitile of the official evenodd face path
(owl-pixel.tsx, assembled=1, idle breath ~0.55), cream tiles.
Compose at 2x then LANCZOS down. No solid owl silhouette.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT.parent  # docs/assets — overwrites README posters
HERO_NAME = {"en": "hero.png", "zh": "hero.zh-CN.png"}
MARKS = ROOT / "marks"
FONTS = ROOT / "fonts"
GLYPHS = ROOT
ZH_GLYPHS = ROOT
OWL_PNG = ROOT / "owl-black.png"


def _rsvg_bin() -> str:
    for cand in (
        shutil.which("rsvg-convert"),
        "/opt/homebrew/bin/rsvg-convert",
        "/usr/local/bin/rsvg-convert",
    ):
        if cand and Path(cand).exists():
            return str(cand)
    raise SystemExit("rsvg-convert not found. brew install librsvg")


RSVG = _rsvg_bin()

SCALE = 2
# Canvas defaults: README 1680×600. `apply_profile("social")` switches to 1280×640.
W1, H1 = 1680, 600
W, H = W1 * SCALE, H1 * SCALE
PROFILE = "readme"
PACT_SHOW_BODY = True
MARQUEE_GAP_1X = 32
MARQUEE_GROUP_1X = 56
HEADLINE_BIAS = 0.5  # 0 = top of the title band, 0.5 = centered


def s(v: float) -> int:
    return int(round(v * SCALE))


def oklch_to_srgb(Lp: float, C: float, Hdeg: float) -> tuple[int, int, int]:
    """CSS-like OKLCH -> sRGB 8-bit (Ottosson OKLab matrices)."""
    L = Lp / 100.0
    h = math.radians(Hdeg)
    a = C * math.cos(h)
    b = C * math.sin(h)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, sv = l_ ** 3, m_ ** 3, s_ ** 3
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * sv
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * sv
    b2 = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * sv

    def enc(c: float) -> int:
        c = max(0.0, min(1.0, c))
        if c <= 0.0031308:
            return int(round(12.92 * c * 255))
        return int(round((1.055 * (c ** (1 / 2.4)) - 0.055) * 255))

    return enc(r), enc(g), enc(b2)


INK = (0x1B, 0x1E, 0x28)  # #1B1E28
CREAM = oklch_to_srgb(95.2, 0.012, 264)  # ~#EBEFF7
MUTED = oklch_to_srgb(68.0, 0.022, 264)  # ~#9198A6
ACCENT = (0x5B, 0x7B, 0xFF)  # #5B7BFF
ACCENT_DEEP = (0x00, 0x2F, 0xA7)  # #002FA7
WHITE = (255, 255, 255)
BORDER_A = int(round(255 * 0.14))
GRID_A = int(round(255 * 0.045))

GEIST_BOLD = FONTS / "Geist-Bold.ttf"
GEIST_REG = FONTS / "Geist-Regular.ttf"
MONO_BOLD = FONTS / "IBMPlexMono-Bold.ttf"
MONO_REG = FONTS / "IBMPlexMono-Regular.ttf"

TITLE_1X = 56
TITLE_TRACK = -0.02
TITLE_GAP_1X = 16  # space between the two title lines (was 8)
NOTE_1X = 19
NOTE_MAX_W = 720
PACT_KICKER = 11
PACT_TITLE = 18
PACT_BODY = 13
MARK_1X = 28
PLATE_1X = 30
OWL_PLATE_1X = 28
PAD_1X = 40
# GitHub Social preview: 1280×640, PNG < 1 MB, keep type ~56px inside edges
# (Twitter/LinkedIn crop ~1.91:1 ≈ 29px from each side of this canvas).
SOCIAL_MAX_BYTES = 1_000_000

# Official face path (viewBox 0 0 806 721), evenodd — same as owl-pixel.tsx.
OWL_FACE_W, OWL_FACE_H = 806.0, 721.0
OWL_FACE_PATH = (
    "M119.212 0C116.659 1.50147 114.557 3.00294 113.506 5.70558C110.503 56.305 "
    "172.514 69.668 196.988 104.802C199.69 105.703 202.093 107.655 205.095 106.304C"
    "209.149 54.3531 144.586 37.0862 119.212 0ZM686.766 0C658.088 36.0352 602.233 "
    "54.5032 599.681 104.652C602.233 106.904 604.335 106.454 607.038 105.103C631.962 "
    "69.2176 706.585 50.2991 686.766 0ZM719.798 69.0674C624.905 138.435 550.283 236.03 "
    "473.708 319.662C469.954 320.563 466.951 323.266 463.498 324.317C439.775 327.17 "
    "421.006 315.158 404.34 300.293C387.374 310.954 371.608 327.77 348.185 324.317C"
    "341.429 322.965 334.972 319.362 329.417 315.308C254.043 232.577 178.52 140.387 "
    "89.1823 70.5689C86.78 70.5689 84.2275 70.5689 81.675 70.5689C66.36 91.7396 "
    "52.2462 113.361 44.1383 137.534C47.2914 211.256 92.0351 277.171 150.442 321.013C"
    "155.547 353.295 161.103 388.129 189.18 409.3C218.459 428.218 264.253 426.266 "
    "288.727 402.243C254.494 400.591 205.696 399.84 207.798 353.295C209.149 350.292 "
    "212.002 349.842 214.555 348.34C254.944 357.199 290.979 376.718 322.81 403.894C"
    "325.513 403.744 324.312 400.591 326.114 399.69C304.342 333.926 234.975 315.008 "
    "178.97 293.987C132.575 254.499 99.6926 197.293 98.1911 138.135C187.528 190.686 "
    "271.31 269.964 343.981 344.887C353.891 363.505 362.449 382.423 368.455 402.393C"
    "377.164 417.858 387.073 433.023 398.184 447.137C408.094 453.743 415.151 440.83 "
    "420.556 434.374C427.162 423.714 431.667 413.053 438.574 402.843C478.362 291.284 "
    "595.327 226.721 682.412 152.999C692.772 149.996 701.18 133.931 711.54 137.384C"
    "702.381 195.791 675.355 255.55 627.308 293.687C571.003 314.707 497.281 333.776 "
    "482.566 403.594C515.148 384.075 550.583 356.899 590.372 348.64C620.401 388.129 "
    "547.73 404.495 518.752 404.045C654.034 470.259 674.304 271.015 749.377 200.145C"
    "773.701 154.951 755.233 100.298 719.798 69.0674ZM776.854 186.182C777.755 197.593 "
    "782.259 208.103 782.86 219.815C824.45 383.024 658.388 571.458 493.077 504.793C"
    "600.582 592.178 774.301 495.033 796.373 369.361C807.033 343.686 807.033 312.155 "
    "803.88 283.627C803.28 248.793 794.721 216.662 781.358 186.182C779.857 186.182 "
    "778.355 186.182 776.854 186.182ZM26.1207 187.683C11.4063 215.611 5.40048 247.892 "
    "3.59872 280.474C-28.6828 444.884 162.904 600.436 310.498 514.402C313.201 511.7 "
    "316.654 509.147 316.805 505.394C149.541 572.059 -22.5268 381.973 24.6193 215.911C"
    "24.319 206.452 30.7753 196.842 26.1207 187.683ZM469.053 489.478C439.775 549.837 "
    "432.868 621.907 415.001 687.672C441.126 630.015 467.402 565.903 479.564 501.49C"
    "476.26 496.685 475.359 490.679 469.053 489.478ZM335.423 490.979C332.12 492.631 "
    "330.618 496.385 329.417 499.688C339.477 577.464 377.914 646.381 399.535 720.253C"
    "385.722 646.381 367.254 568.906 344.432 495.784C342.78 492.031 339.477 490.229 "
    "335.423 490.979Z"
)

PIXEL_GRID = 52
TILE_FILL = 0.58
ASSEMBLED = 1.0
IDLE_BREATH = 1.0  # full-bright static frame
OWL_W_1X = 420  # landing min(420px, 38vw); slightly large on this banner
OWL_RIGHT_PCT = 0.02
OWL_BOTTOM_PCT = 0.0  # unused; owl is vertically centered

_README_PROFILE = {
    "w1": 1680,
    "h1": 600,
    "title_1x": 56,
    "title_gap_1x": 16,
    "note_1x": 19,
    "note_max_w": 720,
    "pact_kicker": 11,
    "pact_title": 18,
    "pact_body": 13,
    "pact_show_body": True,
    "mark_1x": 28,
    "plate_1x": 30,
    "owl_plate_1x": 28,
    "pad_1x": 40,
    "owl_w_1x": 420,
    "owl_right_pct": 0.02,
    "marquee_gap_1x": 32,
    "marquee_group_1x": 56,
    "headline_bias": 0.5,
    "hero_name": {"en": "hero.png", "zh": "hero.zh-CN.png"},
}
_SOCIAL_PROFILE = {
    "w1": 1280,
    "h1": 640,
    "title_1x": 52,
    "title_gap_1x": 12,
    "note_1x": 18,
    "note_max_w": 720,
    "pact_kicker": 11,
    "pact_title": 17,
    "pact_body": 12,
    "pact_show_body": False,
    "mark_1x": 24,
    "plate_1x": 26,
    "owl_plate_1x": 26,
    "pad_1x": 56,
    "owl_w_1x": 340,
    "owl_right_pct": 0.03,
    "marquee_gap_1x": 24,
    "marquee_group_1x": 40,
    "headline_bias": 0.28,
    "hero_name": {"en": "social-preview.png"},
}


def apply_profile(name: str) -> None:
    """Switch canvas. `readme` = README poster; `social` = GitHub OG 1280×640."""
    global W1, H1, W, H, PROFILE, PACT_SHOW_BODY, HERO_NAME
    global TITLE_1X, TITLE_GAP_1X, NOTE_1X, NOTE_MAX_W
    global PACT_KICKER, PACT_TITLE, PACT_BODY
    global MARK_1X, PLATE_1X, OWL_PLATE_1X, PAD_1X, OWL_W_1X, OWL_RIGHT_PCT
    global MARQUEE_GAP_1X, MARQUEE_GROUP_1X, HEADLINE_BIAS
    if name == "social":
        p = _SOCIAL_PROFILE
    elif name == "readme":
        p = _README_PROFILE
    else:
        raise SystemExit(f"unknown profile {name!r} (readme|social)")
    PROFILE = name
    W1, H1 = p["w1"], p["h1"]
    W, H = W1 * SCALE, H1 * SCALE
    TITLE_1X = p["title_1x"]
    TITLE_GAP_1X = p["title_gap_1x"]
    NOTE_1X = p["note_1x"]
    NOTE_MAX_W = p["note_max_w"]
    PACT_KICKER = p["pact_kicker"]
    PACT_TITLE = p["pact_title"]
    PACT_BODY = p["pact_body"]
    PACT_SHOW_BODY = p["pact_show_body"]
    MARK_1X = p["mark_1x"]
    PLATE_1X = p["plate_1x"]
    OWL_PLATE_1X = p["owl_plate_1x"]
    PAD_1X = p["pad_1x"]
    OWL_W_1X = p["owl_w_1x"]
    OWL_RIGHT_PCT = p["owl_right_pct"]
    MARQUEE_GAP_1X = p["marquee_gap_1x"]
    MARQUEE_GROUP_1X = p["marquee_group_1x"]
    HEADLINE_BIAS = p["headline_bias"]
    HERO_NAME = dict(p["hero_name"])


def font(path: Path, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), px)


def crop_alpha(im: Image.Image, pad: int = 0) -> Image.Image:
    im = im.convert("RGBA")
    bbox = im.split()[-1].getbbox()
    if not bbox:
        return im
    if pad:
        x0, y0, x1, y1 = bbox
        bbox = (
            max(0, x0 - pad),
            max(0, y0 - pad),
            min(im.width, x1 + pad),
            min(im.height, y1 + pad),
        )
    return im.crop(bbox)


def tint_glyph(im: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    a = im.convert("RGBA").split()[-1]
    out = Image.new("RGBA", im.size, color + (255,))
    out.putalpha(a)
    return out


def fit(im: Image.Image, max_w: int | None = None, max_h: int | None = None) -> Image.Image:
    if im.width == 0 or im.height == 0:
        return im
    scale = 1.0
    if max_w:
        scale = min(scale, max_w / im.width)
    if max_h:
        scale = min(scale, max_h / im.height)
    if abs(scale - 1.0) < 0.001:
        return im
    nw = max(1, int(round(im.width * scale)))
    nh = max(1, int(round(im.height * scale)))
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def contain(im: Image.Image, box: tuple[int, int]) -> Image.Image:
    im = crop_alpha(im)
    if im.width == 0 or im.height == 0:
        return im
    bw, bh = box
    scale = min(bw / im.width, bh / im.height)
    nw = max(1, int(round(im.width * scale)))
    nh = max(1, int(round(im.height * scale)))
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def rounded_fill(size: tuple[int, int], radius: int, color) -> Image.Image:
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=color
    )
    return im


def round_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255
    )
    return mask


def round_logo(path: Path, size: int, radius: int) -> Image.Image:
    im = Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0))
    out.putalpha(round_mask((size, size), radius))
    return out


def paste(base: Image.Image, img: Image.Image, xy) -> Image.Image:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    x, y = int(round(xy[0])), int(round(xy[1]))
    layer.paste(img, (x, y), img)
    return Image.alpha_composite(base, layer)


def rsvg(svg: Path, width: int, height: int | None = None, fill_rewrite: str | None = None) -> Image.Image:
    src = svg
    tmp = None
    if fill_rewrite is not None:
        txt = svg.read_text(encoding="utf-8")
        txt = txt.replace("currentColor", fill_rewrite)
        tmp = Path(tempfile.mkstemp(suffix=".svg")[1])
        tmp.write_text(txt, encoding="utf-8")
        src = tmp
    cmd = [RSVG, "-w", str(width)]
    if height:
        cmd += ["-h", str(height)]
    cmd += ["--keep-aspect-ratio", str(src)]
    data = subprocess.check_output(cmd)
    if tmp is not None:
        tmp.unlink(missing_ok=True)
    return crop_alpha(Image.open(BytesIO(data)).convert("RGBA"))


def white_plate(icon: Image.Image, plate: int, radius: int, inset: int) -> Image.Image:
    bg = rounded_fill((plate, plate), radius, WHITE + (255,))
    inner = contain(icon, (plate - inset * 2, plate - inset * 2))
    x = (plate - inner.width) // 2
    y = (plate - inner.height) // 2
    bg.paste(inner, (x, y), inner)
    return bg


def tracked_advance(ch: str, fnt: ImageFont.FreeTypeFont, extra: float) -> float:
    return ImageDraw.Draw(Image.new("RGB", (8, 8))).textlength(ch, font=fnt) + extra


def tracked_width(text: str, fnt: ImageFont.FreeTypeFont, tracking_em: float) -> float:
    extra = tracking_em * fnt.size
    w = 0.0
    for i, ch in enumerate(text):
        w += tracked_advance(ch, fnt, extra if i < len(text) - 1 else 0.0)
    return w


def draw_tracked(draw: ImageDraw.ImageDraw, xy, text: str, fnt, fill, tracking_em: float) -> float:
    x, y = xy
    extra = tracking_em * fnt.size
    for i, ch in enumerate(text):
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += tracked_advance(ch, fnt, extra if i < len(text) - 1 else 0.0)
    return x


def wrap_words(text: str, fnt, max_w: int, tracking_em: float = 0.0) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if tracked_width(trial, fnt, tracking_em) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def ellipse_radial(size: tuple[int, int], cx: float, cy: float, rx: float, ry: float) -> Image.Image:
    """White-center elliptical falloff (CSS radial-gradient analogue)."""
    g = ImageOps.invert(Image.radial_gradient("L"))
    gw = max(2, int(round(2 * rx)))
    gh = max(2, int(round(2 * ry)))
    g = g.resize((gw, gh), Image.Resampling.BICUBIC)
    layer = Image.new("L", size, 0)
    layer.paste(g, (int(round(cx - rx)), int(round(cy - ry))))
    return layer


def hash01(i: int, salt: int) -> float:
    """owl-pixel.tsx hash01 — JS Math.sin fractional part."""
    x = math.sin(i * 12.9898 + salt * 78.233) * 43758.5453
    return x - math.floor(x)


def rasterize_face(grid: int) -> list[dict]:
    """52×52 evenodd raster + isolated-speck drop, matching owl-pixel.tsx."""
    pad = 1
    avail = grid - pad * 2
    scale = min(avail / OWL_FACE_W, avail / OWL_FACE_H)
    drawn_w = OWL_FACE_W * scale
    drawn_h = OWL_FACE_H * scale
    ox = (grid - drawn_w) / 2.0
    oy = (grid - drawn_h) / 2.0
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{grid}" height="{grid}" '
        f'viewBox="0 0 {grid} {grid}">'
        f'<rect width="{grid}" height="{grid}" fill="#000000"/>'
        f'<g transform="translate({ox:.8f},{oy:.8f}) scale({scale:.10f})">'
        f'<path fill="#ffffff" fill-rule="evenodd" d="{OWL_FACE_PATH}"/>'
        f"</g></svg>"
    )
    tmp = Path(tempfile.mkstemp(suffix=".svg")[1])
    tmp.write_text(svg, encoding="utf-8")
    data = subprocess.check_output(
        [RSVG, "-w", str(grid), "-h", str(grid), str(tmp)]
    )
    tmp.unlink(missing_ok=True)
    im = Image.open(BytesIO(data)).convert("RGB")
    if im.size != (grid, grid):
        im = im.resize((grid, grid), Image.Resampling.NEAREST)
    pix = im.load()
    lum = [0.0] * (grid * grid)
    for y in range(grid):
        for x in range(grid):
            r, g, b = pix[x, y]
            lum[y * grid + x] = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0

    def isolated(x: int, y: int) -> bool:
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if nx < 0 or ny < 0 or nx >= grid or ny >= grid:
                    continue
                if lum[ny * grid + nx] > 0.2:
                    return False
        return True

    cells: list[dict] = []
    for y in range(grid):
        for x in range(grid):
            a = lum[y * grid + x]
            if a <= 0.2 or isolated(x, y):
                continue
            edge = 0
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if nx < 0 or ny < 0 or nx >= grid or ny >= grid or lum[ny * grid + nx] <= 0.2:
                        edge += 1
            i = len(cells)
            cells.append(
                {
                    "gx": x,
                    "gy": y,
                    "opacity": a,
                    "edge": edge / 8.0,
                    "size": 0.55 + 0.7 * hash01(i, 3),
                    "seed": i + 1,
                }
            )
    return cells


def build_pixel_owl(css_w: int, css_h: int) -> tuple[Image.Image, int]:
    """Static assembled=1 digitile. Cream tiles, ghosted watermark alphas."""
    cells = rasterize_face(PIXEL_GRID)
    cell_w = css_w / PIXEL_GRID
    cell_h = css_h / PIXEL_GRID
    light_x = css_w * 0.28
    light_y = css_h * 0.22
    light_range = math.hypot(css_w, css_h) * 0.72
    tile_base = min(cell_w, cell_h) * TILE_FILL
    # Draw squares into an L mask (straight alpha). ImageDraw RGBA fill is
    # premultiplied and would double-darken under alpha_composite.
    mask = Image.new("L", (css_w, css_h), 0)
    md = ImageDraw.Draw(mask)
    for cell in cells:
        x = (cell["gx"] + 0.5) * cell_w
        y = (cell["gy"] + 0.5) * cell_h
        lit = max(0.0, 1.0 - math.hypot(x - light_x, y - light_y) / light_range)
        shade = min(1.0, 0.55 + 0.7 * lit * lit)
        tile = tile_base * cell["size"]
        # User: cell.opacity * ~0.7 * shade, tiles ~0.35–0.55 so grid shows.
        a = cell["opacity"] * shade
        a = max(0.0, min(1.0, a))
        alpha = int(round(a * 255))
        if alpha < 10:
            continue
        side = max(1, int(round(tile)))
        x0 = int(round(x - side / 2.0))
        y0 = int(round(y - side / 2.0))
        md.rectangle([x0, y0, x0 + side - 1, y0 + side - 1], fill=alpha)
    body = Image.new("RGBA", (css_w, css_h), CREAM + (255,))
    body.putalpha(mask)
    return body, len(cells)


PIXEL_OWL_CELLS = 0


def paint_atmosphere(im: Image.Image) -> Image.Image:
    global PIXEL_OWL_CELLS
    # Glow sits with the bottom-right wash, not the old center-right blob.
    cx, cy = 0.82 * W, 0.50 * H
    rx, ry = 0.42 * W, 0.48 * H
    falloff = ellipse_radial((W, H), cx, cy, rx, ry)

    glow = Image.new("RGBA", (W, H), ACCENT + (0,))
    glow.putalpha(falloff.point(lambda p: int(p * 0.12)))
    glow = glow.filter(ImageFilter.GaussianBlur(s(8)))
    im = Image.alpha_composite(im, glow)

    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(grid)
    step = s(56)
    col = CREAM + (GRID_A,)
    lw = max(1, s(1))
    for x in range(0, W, step):
        d.line([(x, 0), (x, H - 1)], fill=col, width=lw)
    for y in range(0, H, step):
        d.line([(0, y), (W - 1, y)], fill=col, width=lw)
    ga = ImageChops.multiply(grid.split()[-1], falloff)
    grid.putalpha(ga)
    im = Image.alpha_composite(im, grid)

    owl_w = s(OWL_W_1X)
    owl_h = int(round(owl_w * OWL_FACE_H / OWL_FACE_W))
    wash, n_cells = build_pixel_owl(owl_w, owl_h)
    PIXEL_OWL_CELLS = n_cells
    wx = int(round(W - OWL_RIGHT_PCT * W - owl_w))
    wy = int(round((H - owl_h) / 2))
    im = paste(im, wash, (wx, wy))
    return im


def line_icon(kind: str, size: int, color: tuple[int, int, int], width: int) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = max(2, int(round(size * 0.14)))
    w = max(2, width)
    if kind == "monitor":
        x0, y0 = m, int(size * 0.16)
        x1, y1 = size - m - 1, int(size * 0.62)
        d.rounded_rectangle((x0, y0, x1, y1), radius=size // 10, outline=color, width=w)
        base_y = int(size * 0.82)
        d.line([(size // 2, y1), (size // 2, base_y - 1)], fill=color, width=w)
        bw = int(size * 0.28)
        d.line([(size // 2 - bw, base_y), (size // 2 + bw, base_y)], fill=color, width=w)
    elif kind == "terminal":
        x0, y0, x1, y1 = m, int(size * 0.18), size - m - 1, size - m - 1
        d.rounded_rectangle((x0, y0, x1, y1), radius=size // 8, outline=color, width=w)
        py = int(size * 0.46)
        px = x0 + int(size * 0.20)
        d.line(
            [(px, py - int(size * 0.10)), (px + int(size * 0.12), py), (px, py + int(size * 0.10))],
            fill=color, width=w, joint="curve",
        )
        d.line(
            [(px + int(size * 0.20), py + int(size * 0.10)), (x1 - int(size * 0.18), py + int(size * 0.10))],
            fill=color, width=max(2, w - 1),
        )
    else:
        d.ellipse((m, m, size - m - 1, size - m - 1), outline=color, width=w)
    return im


def build_logos() -> dict[str, Image.Image]:
    mark = (s(MARK_1X), s(MARK_1X))
    plate = s(PLATE_1X)
    stroke = CREAM
    logos: dict[str, Image.Image] = {}
    logos["local"] = line_icon("monitor", s(MARK_1X), stroke, s(1.6))
    logos["ssh"] = line_icon("terminal", s(MARK_1X), stroke, s(1.6))
    logos["docker"] = contain(rsvg(MARKS / "docker.svg", s(72)), mark)
    logos["e2b"] = contain(rsvg(MARKS / "e2b.svg", s(64)), mark)
    logos["daytona"] = contain(rsvg(MARKS / "daytona.svg", s(64)), mark)
    logos["claude"] = contain(rsvg(MARKS / "claude-code.svg", s(64)), mark)
    logos["codex"] = contain(rsvg(MARKS / "codex.svg", s(64)), mark)
    logos["pi"] = white_plate(rsvg(MARKS / "pi.svg", s(48), fill_rewrite="#111111"), plate, s(6), s(7))
    logos["opencode"] = white_plate(
        rsvg(MARKS / "opencode.svg", s(48), fill_rewrite="#111111"), plate, s(6), s(7)
    )
    logos["nooa"] = contain(rsvg(MARKS / "nooa.svg", s(64)), mark)
    logos["miniswe"] = contain(rsvg(MARKS / "miniswe.svg", s(64)), mark)
    logos["dsh"] = contain(rsvg(MARKS / "dsh.svg", s(64)), mark)
    return logos


SC_INDEX = 0

COPY = {
    "en": {
        "titleA": "Configure Agent Eval Once,",
        "accentA": "Once",
        "titleB": "Run It Anywhere.",
        "accentB": "Anywhere",
        "note": "Swap the agent under test with plugins. Teach the Agent to run evals with the CLI and skills.",
        "plugins": "+ via plugins",
        "pacts": [
            ("SWITCH", "Swap the agent under test in one line",
             "No changes to ageval: install a plugin, flip one line of config, and the same dataset runs as-is."),
            ("TEACH", "Teach the Agent automated evaluation",
             "Install the CLI and skills so the Agent can design, convert benchmarks, and run evaluations."),
            ("HUB", "Share and reuse on Hub",
             "Share or reuse datasets, plugins, and agent configs on ageval Hub, and upload evaluation results."),
        ],
    },
    "zh": {
        "titleA": "配置一次 Agent Eval，",
        "accentA": "一次",
        "titleB": "任意切换运行",
        "accentB": "任意",
        "note": "装插件换待评测 Agent。装上 CLI 和 skill，Agent 能自己跑评测。",
        "plugins": "+ 经插件",
        "pacts": [
            ("SWITCH", "一键切换待评测 Agent",
             "换 Agent 不改 ageval：装插件，在配置里切一行，同一份 dataset 原样跑。"),
            ("TEACH", "让 Agent 学会自动评测",
             "装上 CLI 和 skill，让 Agent 能设计、转化 benchmark，并自动跑评测。"),
            ("HUB", "在 Hub 上分享与复用",
             "在 ageval Hub 上分享或复用 dataset、插件和 Agent 配置，并上传评测结果。"),
        ],
    },
}

ENV_KEYS = ["local", "docker", "e2b", "ssh", "daytona"]
AGENT_KEYS = ["claude", "codex", "pi", "opencode", "nooa", "miniswe", "dsh"]


def sc_font(bold: bool, px: int) -> ImageFont.FreeTypeFont:
    shipped = FONTS / ("NotoSansSC-Bold.otf" if bold else "NotoSansSC-Regular.otf")
    if shipped.exists():
        return ImageFont.truetype(str(shipped), px)
    mac = [
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2 if bold else 0),
        ("/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc", 1),
    ]
    for path, index in mac:
        if Path(path).exists():
            return ImageFont.truetype(path, px, index=index)
    raise FileNotFoundError("no CJK font: add NotoSansSC to fonts/ or use macOS Hiragino/Heiti")


def title_font(locale: str) -> ImageFont.FreeTypeFont:
    return sc_font(True, s(TITLE_1X)) if locale == "zh" else font(GEIST_BOLD, s(TITLE_1X))


def note_font(locale: str) -> ImageFont.FreeTypeFont:
    return sc_font(False, s(NOTE_1X)) if locale == "zh" else font(GEIST_REG, s(NOTE_1X))


def pact_title_font(locale: str) -> ImageFont.FreeTypeFont:
    return sc_font(True, s(PACT_TITLE)) if locale == "zh" else font(GEIST_BOLD, s(PACT_TITLE))


def pact_body_font(locale: str) -> ImageFont.FreeTypeFont:
    return sc_font(False, s(PACT_BODY)) if locale == "zh" else font(GEIST_REG, s(PACT_BODY))


def title_track(locale: str) -> float:
    return 0.0 if locale == "zh" else TITLE_TRACK


def wrap_mixed(text: str, fnt, max_w: int, tracking_em: float = 0.0) -> list[str]:
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in "._-+/"):
            buf += ch
        else:
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
    if buf:
        tokens.append(buf)
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        trial = cur + tok
        if tracked_width(trial, fnt, tracking_em) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur.rstrip())
            cur = tok if tok != " " else ""
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [text]


def split_note(note: str) -> list[str]:
    if "。" in note:
        parts = [p for p in note.split("。") if p]
        if len(parts) >= 2:
            return [parts[0] + "。", "。".join(parts[1:]) + ("。" if note.endswith("。") else "")]
    if ". " in note:
        a, b = note.split(". ", 1)
        return [a + ".", b]
    return [note]


def lockup_bottom() -> int:
    pad = s(PAD_1X)
    plate_h = s(OWL_PLATE_1X)
    wm = fit(crop_alpha(Image.open(GLYPHS / "wordmark.png").convert("RGBA")), max_h=s(24))
    return pad + max(plate_h, wm.height)


def marquee_rule_y() -> int:
    return H - s(32) - s(PLATE_1X) - s(14)


def pact_y1() -> int:
    return marquee_rule_y() - s(16)


def measure_pact_h(locale: str) -> int:
    d = ImageDraw.Draw(Image.new("RGBA", (16, 16)))
    cell_pad = s(14)
    kf = font(MONO_REG, s(PACT_KICKER))
    tf = pact_title_font(locale)
    bf = pact_body_font(locale)
    k_h = d.textbbox((0, 0), "H", font=kf)
    k_h = k_h[3] - k_h[1]
    pad_x = s(PAD_1X)
    col_w = (W - pad_x * 2) // 3
    body_max = col_w - cell_pad * 2
    t_lh = int(round(s(PACT_TITLE) * 1.25))
    b_lh = int(round(s(PACT_BODY) * 1.4))
    title_lines = 1
    body_lines = 0
    for _k, title, body in COPY[locale]["pacts"]:
        title_lines = max(title_lines, len(wrap_mixed(title, tf, body_max)))
        if PACT_SHOW_BODY:
            body_lines = max(body_lines, len(wrap_mixed(body, bf, body_max)))
    body_block = (s(6) + body_lines * b_lh) if PACT_SHOW_BODY else 0
    return cell_pad + k_h + s(6) + title_lines * t_lh + body_block + cell_pad


def measure_headline_h(locale: str) -> int:
    d = ImageDraw.Draw(Image.new("RGBA", (16, 16)))
    tf = title_font(locale)
    nf = note_font(locale)
    th = d.textbbox((0, 0), "Hg", font=tf)
    th = th[3] - th[1]
    nbb = d.textbbox((0, 0), "Hg", font=nf)
    n_h = nbb[3] - nbb[1]
    n_lh = int(round(s(NOTE_1X) * 1.55))
    notes = split_note(COPY[locale]["note"])
    return th + s(TITLE_GAP_1X) + th + s(20) + n_lh * (len(notes) - 1) + n_h


def headline_top(locale: str) -> int:
    top = lockup_bottom() + s(8)
    bot = pact_y1() - measure_pact_h(locale)
    group = measure_headline_h(locale)
    band = bot - top
    y = top + max(0, int(round((band - group) * HEADLINE_BIAS)))
    if y + group > bot - s(8):
        y = max(top, bot - group - s(8))
    return y


def draw_lockup(im: Image.Image) -> Image.Image:
    pad = s(PAD_1X)
    plate = round_logo(OWL_PNG, s(OWL_PLATE_1X), s(8))
    wm_src = crop_alpha(Image.open(GLYPHS / "wordmark.png").convert("RGBA"))
    wordmark = tint_glyph(wm_src, CREAM)
    wordmark = fit(wordmark, max_h=s(24))
    ident_h = max(plate.height, wordmark.height)
    y = pad + (ident_h - plate.height) // 2
    im = paste(im, plate, (pad, y))
    wy = pad + (ident_h - wordmark.height) // 2
    im = paste(im, wordmark, (pad + plate.width + s(12), wy))
    return im


def draw_accent_line(draw, y, line: str, accent: str, fnt, tracking: float) -> None:
    i = line.find(accent)
    w = tracked_width(line, fnt, tracking)
    x = (W - w) / 2
    if i < 0:
        draw_tracked(draw, (x, y), line, fnt, CREAM + (255,), tracking)
        return
    before, acc, after = line[:i], accent, line[i + len(accent):]
    extra = tracking * fnt.size
    if before:
        x = draw_tracked(draw, (x, y), before, fnt, CREAM + (255,), tracking) + extra
    x = draw_tracked(draw, (x, y), acc, fnt, ACCENT + (255,), tracking)
    if after:
        draw_tracked(draw, (x + extra, y), after, fnt, CREAM + (255,), tracking)


def draw_headline(im: Image.Image, locale: str, title_y: int) -> Image.Image:
    d = ImageDraw.Draw(im)
    copy = COPY[locale]
    tf = title_font(locale)
    nf = note_font(locale)
    track = title_track(locale)
    th = d.textbbox((0, 0), "Hg", font=tf)
    th = th[3] - th[1]
    draw_accent_line(d, title_y, copy["titleA"], copy["accentA"], tf, track)
    y2 = title_y + th + s(TITLE_GAP_1X)
    draw_accent_line(d, y2, copy["titleB"], copy["accentB"], tf, track)
    nbb = d.textbbox((0, 0), "Hg", font=nf)
    n_lh = int(round(s(NOTE_1X) * 1.55))
    note_top = y2 + th + s(20)
    for i, ln in enumerate(split_note(copy["note"])):
        lw = tracked_width(ln, nf, 0)
        nx = (W - lw) / 2
        ny = note_top + i * n_lh
        d.text((nx - nbb[0], ny), ln, font=nf, fill=MUTED + (255,))
    return im


def draw_pact(im: Image.Image, locale: str, y1: int) -> Image.Image:
    d = ImageDraw.Draw(im)
    pad_x = s(PAD_1X)
    inner_w = W - pad_x * 2
    cols = 3
    col_w = inner_w // cols
    cell_pad = s(14)
    kf = font(MONO_REG, s(PACT_KICKER))
    tf = pact_title_font(locale)
    bf = pact_body_font(locale)
    k_bb = d.textbbox((0, 0), "H", font=kf)
    t_bb = d.textbbox((0, 0), "Hg", font=tf)
    b_bb = d.textbbox((0, 0), "Hg", font=bf)
    k_h = k_bb[3] - k_bb[1]
    t_lh = int(round(s(PACT_TITLE) * 1.25))
    b_lh = int(round(s(PACT_BODY) * 1.4))
    body_max = col_w - cell_pad * 2
    pacts = COPY[locale]["pacts"]
    wrapped_t = [wrap_mixed(p[1], tf, body_max) for p in pacts]
    wrapped_b = [wrap_mixed(p[2], bf, body_max) for p in pacts] if PACT_SHOW_BODY else [[] for _ in pacts]
    title_lines = max(len(w) for w in wrapped_t)
    body_lines = max((len(w) for w in wrapped_b), default=0) if PACT_SHOW_BODY else 0
    body_block = (s(6) + body_lines * b_lh) if PACT_SHOW_BODY else 0
    strip_h = cell_pad + k_h + s(6) + title_lines * t_lh + body_block + cell_pad
    y0 = y1 - strip_h
    border = CREAM + (BORDER_A,)
    lw = max(1, s(1))
    d.line([(pad_x, y0), (pad_x + inner_w, y0)], fill=border, width=lw)
    d.line([(pad_x, y1), (pad_x + inner_w, y1)], fill=border, width=lw)
    for i in range(1, cols):
        x = pad_x + i * col_w
        d.line([(x, y0), (x, y1)], fill=border, width=lw)
    for i, (kicker, _title, _body) in enumerate(pacts):
        x0 = pad_x + i * col_w + cell_pad
        y = y0 + cell_pad
        draw_tracked(d, (x0, y), kicker, kf, MUTED + (255,), 0.14)
        y += k_h + s(6)
        for ln in wrapped_t[i]:
            d.text((x0 - t_bb[0], y), ln, font=tf, fill=CREAM + (255,))
            y += t_lh
        if PACT_SHOW_BODY:
            y += s(6)
            for ln in wrapped_b[i]:
                d.text((x0 - b_bb[0], y), ln, font=bf, fill=MUTED + (255,))
                y += b_lh
    return im


def draw_marquee(im: Image.Image, logos: dict[str, Image.Image], rule_y: int, locale: str) -> Image.Image:
    d = ImageDraw.Draw(im)
    pad_x = s(PAD_1X)
    inner_w = W - pad_x * 2
    label = COPY[locale]["plugins"]
    mf = sc_font(False, s(12)) if locale == "zh" else font(MONO_REG, s(12))
    plug_w = int(d.textlength(label, font=mf))
    lbb = d.textbbox((0, 0), label, font=mf)
    gap = s(MARQUEE_GAP_1X)
    group = s(MARQUEE_GROUP_1X)
    total = 0
    for k in ENV_KEYS:
        total += logos[k].width
    total += gap * (len(ENV_KEYS) - 1) + group
    for k in AGENT_KEYS:
        total += logos[k].width
    total += gap * (len(AGENT_KEYS) - 1) + group + plug_w
    x = (W - total) // 2
    row_h = max(s(PLATE_1X), *(logos[k].height for k in ENV_KEYS + AGENT_KEYS))
    cy = rule_y + s(14) + row_h // 2
    for i, k in enumerate(ENV_KEYS):
        logo = logos[k]
        im = paste(im, logo, (x, cy - logo.height // 2))
        x += logo.width + (group if i == len(ENV_KEYS) - 1 else gap)
    for i, k in enumerate(AGENT_KEYS):
        logo = logos[k]
        im = paste(im, logo, (x, cy - logo.height // 2))
        x += logo.width + (group if i == len(AGENT_KEYS) - 1 else gap)
    d = ImageDraw.Draw(im)
    ly = cy - (lbb[3] - lbb[1]) // 2 - lbb[1]
    d.text((x, ly), label, font=mf, fill=MUTED + (255,))
    return im


def render(locale: str) -> Image.Image:
    im = Image.new("RGBA", (W, H), INK + (255,))
    im = paint_atmosphere(im)
    logos = build_logos()
    im = draw_lockup(im)
    im = draw_headline(im, locale, headline_top(locale))
    im = draw_pact(im, locale, pact_y1())
    im = draw_marquee(im, logos, marquee_rule_y(), locale)
    return im


def save_locale(locale: str) -> None:
    im = render(locale)
    rgb = Image.new("RGB", im.size, INK)
    rgb.paste(im, mask=im.split()[-1])
    hero = rgb.resize((W1, H1), Image.Resampling.LANCZOS)
    hero_path = ASSETS / HERO_NAME[locale]
    hero.save(hero_path, "PNG", optimize=True, compress_level=9)
    nbytes = hero_path.stat().st_size
    print(
        f"{PROFILE}/{locale} {hero.size} -> {hero_path} "
        f"{nbytes / 1024:.0f}KB "
        f"title_y={headline_top(locale)} pact_h={measure_pact_h(locale)}"
    )
    if PROFILE == "social" and nbytes >= SOCIAL_MAX_BYTES:
        raise SystemExit(f"social-preview is {nbytes} bytes; GitHub limit is {SOCIAL_MAX_BYTES}")


def main() -> None:
    import sys
    args = [a for a in sys.argv[1:] if a]
    if args and args[0] in ("social", "--social"):
        apply_profile("social")
        save_locale("en")
        return
    apply_profile("readme")
    locales = [a for a in args if a not in ("readme", "--readme")] or ["en", "zh"]
    for loc in locales:
        save_locale(loc)


if __name__ == "__main__":
    main()
