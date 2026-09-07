# README hero source

`render_hero.py` bakes the README posters (Pillow, 1680×600, compose at 2× then LANCZOS) and the GitHub Social preview (1280×640, English):

- `docs/assets/hero.png`
- `docs/assets/hero.zh-CN.png`
- `docs/assets/social-preview.png` — GitHub **Settings → Social preview** (PNG, 1280×640, under 1 MB)

`render_demo_cover.py` bakes `docs/assets/demo-cover.png` (Pillow + system Chrome, 1513×722): it screenshots `docs/assets/why-ageval.svg` and centers the YouTube play button, so the README's why-diagram doubles as the demo-video entry. It uses Chrome headless (`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`) instead of rsvg-convert — librsvg drops the export's `<symbol>/<use>` icons and emoji glyphs. Same venv.

This folder is the editable source: copy, type size, and owl position live in the script. Lockup is `owl-black.png` / `owl-black.svg`; pixel wash is `owl-wash.png` (also generated in-script).

The Social preview is the Open Graph image GitHub serves when someone shares the **repository URL** (Slack, Discord, X, LinkedIn). It is not shown on the GitHub Releases page itself; release links get GitHub's auto-generated release card. Upload `social-preview.png` in the repo Settings — GitHub has no API for this field.

## Export

Needs Pillow and `rsvg-convert` (`brew install librsvg`). Homebrew Python has no Pillow, so use the local venv:

```bash
cd docs/assets/hero-source
python3 -m venv .venv          # once
.venv/bin/pip install pillow   # once
.venv/bin/python render_hero.py          # README 1680×600 en+zh
.venv/bin/python render_hero.py social   # GitHub Social preview 1280×640 en
```

Output names match the README embeds / Settings upload. `rsvg-convert` is resolved from PATH, then Homebrew. `.venv/` is gitignored.
