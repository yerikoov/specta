"""Build the terminal animation frames of the agents (dev tool, output is committed).

    python scripts/build_term_art.py [--cols 34]

Needs Node, Google Chrome and chafa (brew install chafa). Steps: blobSVG → SVG frames (Node) → PNG (Chrome headless)
→ ANSI art (chafa) → app/review/term_art/<agent>/<frame>.ans (only colour codes kept, cursor controls stripped).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "review" / "term_art"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BG = "1c1d1f"      # the colour the agents are rendered on: close to a dark terminal, so anti-aliased edges blend in.
# Chrome shifts it by ±1 and anti-aliasing leaves near-BG pixels: everything within TOL of it becomes «terminal default
# background», so no box is drawn around the agent on any dark terminal.
BGRGB = tuple(int(BG[i:i + 2], 16) for i in (0, 2, 4))
TOL = 6
COMPLEMENT = {"▀": "▄", "▄": "▀", "▌": "▐", "▐": "▌"}     # a glyph and the same cell with fg/bg swapped
TOKEN = re.compile(r"\x1b\[([0-9;]*)m|(\n)|(.)", re.S)


def _near_bg(c) -> bool:
    return c is not None and all(abs(a - b) <= TOL for a, b in zip(c, BGRGB))


def normalize(ans: str) -> str:
    """Parse chafa's SGR output cell by cell, resolve reverse video, make background cells transparent and re-emit
    plain `fg;bg;glyph` cells (no reverse, no cursor codes) with colours only where the state changes."""
    rows, row = [], []
    fg = bg = None
    rev = False
    for m in TOKEN.finditer(ans):
        params, nl, ch = m.groups()
        if nl is not None:
            rows.append(row)
            row = []
        elif ch is not None:
            f, b = (bg, fg) if rev else (fg, bg)
            row.append((ch, f, b))
        else:
            p = [int(x) for x in params.split(";") if x] or [0]
            k = 0
            while k < len(p):
                if p[k] == 0:
                    fg = bg = None
                    rev = False
                elif p[k] == 7:
                    rev = True
                elif p[k] == 27:
                    rev = False
                elif p[k] == 39:
                    fg = None
                elif p[k] == 49:
                    bg = None
                elif p[k] in (38, 48) and p[k + 1:k + 2] == [2]:
                    c = tuple(p[k + 2:k + 5])
                    if p[k] == 38:
                        fg = c
                    else:
                        bg = c
                    k += 4
                k += 1
    rows.append(row)
    out = []
    for cells in rows:
        line, cur = [], (None, None)
        for ch, f, b in cells:
            if ch == " ":
                f = None                                   # the ink colour of a space never shows
            if _near_bg(b):
                b = None
            if _near_bg(f) and ch != " ":
                if ch in COMPLEMENT and b is not None:     # ▀ in BG colour over colour C  ==  ▄ in C over nothing
                    ch, f, b = COMPLEMENT[ch], b, None
                elif ch == "█":
                    ch, f, b = " ", None, None
            if (f, b) != cur:
                codes = ["0"]
                if f:
                    codes.append("38;2;%d;%d;%d" % f)
                if b:
                    codes.append("48;2;%d;%d;%d" % b)
                line.append(f"\x1b[{';'.join(codes)}m")
                cur = (f, b)
            line.append(ch)
        out.append("".join(line) + "\x1b[0m")
    while out and out[-1] == "\x1b[0m":
        out.pop()
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cols", type=int, default=40)
    ap.add_argument("--px", type=int, default=480)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="term_art_"))
    subprocess.run(["node", str(ROOT / "scripts" / "build_term_art.mjs"), str(tmp / "svg")], check=True, cwd=ROOT)
    names = (tmp / "svg" / "manifest.txt").read_text().split()
    prof = tmp / "chrome"
    if OUT.exists():
        shutil.rmtree(OUT)
    for n in names:
        svg, png = tmp / "svg" / f"{n}.svg", tmp / "png" / f"{n}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        page = tmp / "svg" / f"{n}.html"
        page.write_text(f'<!doctype html><style>html,body{{margin:0;background:#{BG}}}svg{{width:{a.px}px;height:{a.px}px;display:block}}</style>'
                        + svg.read_text())
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={prof}", "--no-first-run",
                        f"--force-device-scale-factor=1", f"--window-size={a.px},{a.px}", f"--screenshot={png}", page.as_uri()],
                       check=True, capture_output=True)
        ans = subprocess.run(["chafa", "-f", "symbols", "-c", "full", "--symbols", "half+block+space",
                              "-s", f"{a.cols}x{a.cols // 2}", "--dither", "none",
                              "--work", "9", "--polite", "on", "--animate", "off", str(png)],
                             check=True, capture_output=True, text=True).stdout
        # keep colours and text only; drop cursor movement / hide-show codes
        clean = normalize(re.sub(r"\x1b\[(?![0-9;]*m)[0-9;?]*[A-Za-z]", "", ans).rstrip("\n"))
        dst = OUT / f"{n}.ans"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(clean + "\n")
    print(len(names), "frames →", OUT.relative_to(ROOT))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
