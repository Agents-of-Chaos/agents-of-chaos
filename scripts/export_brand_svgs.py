from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageFilter
from skimage import measure, morphology


ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "public" / "brand"
MARK_PNG = BRAND_DIR / "aoc-mark-reference.png"
FONT_PATH = ROOT / "public" / "fonts" / "AgentsSans.ttf"

FILL = "#F7F3EA"
BACKGROUNDS = {
    "black": "#050707",
    "dark-gray": "#171B1B",
}


@dataclass(frozen=True)
class TextRun:
    paths: list[str]
    width: float
    height: float


def fmt(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def contour_to_cubic_path(points: list[tuple[float, float]]) -> str:
    if len(points) < 3:
        return ""
    cleaned: list[tuple[float, float]] = []
    for point in points:
        if not cleaned or abs(cleaned[-1][0] - point[0]) > 0.01 or abs(cleaned[-1][1] - point[1]) > 0.01:
            cleaned.append(point)
    if len(cleaned) > 1 and abs(cleaned[0][0] - cleaned[-1][0]) < 0.01 and abs(cleaned[0][1] - cleaned[-1][1]) < 0.01:
        cleaned.pop()
    if len(cleaned) < 3:
        return ""

    commands = [f"M {fmt(cleaned[0][0])} {fmt(cleaned[0][1])}"]
    count = len(cleaned)
    for index, current in enumerate(cleaned):
        target = cleaned[(index + 1) % count]
        previous = cleaned[index - 1]
        following = cleaned[(index + 2) % count]
        c1 = (
            current[0] + (target[0] - previous[0]) / 6,
            current[1] + (target[1] - previous[1]) / 6,
        )
        c2 = (
            target[0] - (following[0] - current[0]) / 6,
            target[1] - (following[1] - current[1]) / 6,
        )
        commands.append(
            "C "
            f"{fmt(c1[0])} {fmt(c1[1])} "
            f"{fmt(c2[0])} {fmt(c2[1])} "
            f"{fmt(target[0])} {fmt(target[1])}"
        )
    commands.append("Z")
    return " ".join(commands)


def trace_mark_path() -> tuple[str, tuple[float, float, float, float]]:
    image = Image.open(MARK_PNG).convert("RGBA")
    alpha = np.asarray(image.getchannel("A"))
    visible = alpha > 12
    ys, xs = np.nonzero(visible)
    if len(xs) == 0:
        raise RuntimeError(f"No visible mark pixels in {MARK_PNG}")

    pad = 4
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(alpha.shape[1], int(xs.max()) + pad + 1)
    y1 = min(alpha.shape[0], int(ys.max()) + pad + 1)

    upsample = 6
    alpha_crop = Image.fromarray(alpha[y0:y1, x0:x1], mode="L")
    enlarged = alpha_crop.resize(
        (alpha_crop.width * upsample, alpha_crop.height * upsample),
        Image.Resampling.LANCZOS,
    ).filter(ImageFilter.GaussianBlur(1.15))
    mask = np.asarray(enlarged) > 76
    mask = morphology.binary_closing(mask, morphology.square(5))
    ys, xs = np.nonzero(mask)
    hx0 = int(xs.min()) - 2
    hy0 = int(ys.min()) - 2
    hx1 = int(xs.max()) + 3
    hy1 = int(ys.max()) + 3
    cropped = mask[max(0, hy0) : min(mask.shape[0], hy1), max(0, hx0) : min(mask.shape[1], hx1)]
    padded = np.pad(cropped.astype(float), 1)

    paths: list[str] = []
    for contour in measure.find_contours(padded, 0.5):
        if len(contour) < 6:
            continue
        contour = measure.approximate_polygon(contour, tolerance=4.2)
        points = [
            (
                float(x0 + (x - 1 + max(0, hx0)) / upsample),
                float(y0 + (y - 1 + max(0, hy0)) / upsample),
            )
            for y, x in contour
        ]
        path = contour_to_cubic_path(points)
        if not path:
            continue
        paths.append(path)

    return " ".join(paths), (float(x0), float(y0), float(x1), float(y1))


def text_to_paths(text: str, size: float, tracking: float = 0) -> TextRun:
    font = TTFont(FONT_PATH)
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    units = font["head"].unitsPerEm
    scale = size / units

    x_cursor = 0.0
    paths: list[str] = []
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for char in text:
        if char == " ":
            space_width = hmtx.metrics.get("space", (330, 0))[0] * scale
            x_cursor += space_width + tracking
            continue
        glyph_name = cmap.get(ord(char))
        if not glyph_name:
            continue
        glyph = glyph_set[glyph_name]
        pen = SVGPathPen(glyph_set)
        transform_pen = TransformPen(pen, (scale, 0, 0, -scale, x_cursor, 0))
        glyph.draw(transform_pen)
        d = pen.getCommands()
        if d:
            paths.append(d)
            raw_glyph = glyf[glyph_name]
            if raw_glyph.numberOfContours:
                bounds = (raw_glyph.xMin, raw_glyph.yMin, raw_glyph.xMax, raw_glyph.yMax)
                gx0, gy0, gx1, gy1 = bounds
                min_x = min(min_x, x_cursor + gx0 * scale)
                min_y = min(min_y, -gy1 * scale)
                max_x = max(max_x, x_cursor + gx1 * scale)
                max_y = max(max_y, -gy0 * scale)
        advance = hmtx.metrics[glyph_name][0] * scale
        x_cursor += advance + tracking

    width = max_x - min_x if min_x != float("inf") else 0
    height = max_y - min_y if min_y != float("inf") else 0
    return TextRun(paths=paths, width=width, height=height)


def path_group(paths: list[str], x: float, y: float, fill: str = FILL) -> str:
    joined = "\n    ".join(f'<path d="{d}" />' for d in paths)
    return f'<g transform="translate({fmt(x)} {fmt(y)})" fill="{fill}">\n    {joined}\n  </g>'


def svg_shell(width: int, height: int, body: str, title: str, background: str | None = None) -> str:
    bg = f'\n  <rect width="100%" height="100%" fill="{background}" />' if background else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">
  <title id="title">{title}</title>{bg}
  {body}
</svg>
'''


def write_svg_set(stem: str, width: int, height: int, body: str, title: str) -> None:
    (BRAND_DIR / f"{stem}.svg").write_text(
        svg_shell(width, height, body, title),
        encoding="utf-8",
    )
    for suffix, color in BACKGROUNDS.items():
        (BRAND_DIR / f"{stem}-{suffix}.svg").write_text(
            svg_shell(width, height, body, f"{title} on {suffix.replace('-', ' ')}", background=color),
            encoding="utf-8",
        )


def mark_group(mark_path: str, source_box: tuple[float, float, float, float], cx: float, y: float, width: float) -> str:
    x0, y0, x1, y1 = source_box
    source_width = x1 - x0
    scale = width / source_width
    x = cx - width / 2 - x0 * scale
    return (
        f'<g transform="translate({fmt(x)} {fmt(y - y0 * scale)}) scale({fmt(scale)})" '
        f'fill="{FILL}" fill-rule="evenodd">\n'
        f'    <path d="{mark_path}" />\n'
        f'  </g>'
    )


def write_logo_agents(mark_path: str, box: tuple[float, float, float, float]) -> None:
    width, height = 960, 760
    center = width / 2
    mark = mark_group(mark_path, box, center, 58, 330)
    agents = text_to_paths("AGENTS", 82, tracking=34)
    of_chaos = text_to_paths("OF CHAOS", 52, tracking=32)
    agents_group = path_group(agents.paths, center - agents.width / 2, 528)
    chaos_group = path_group(of_chaos.paths, center - of_chaos.width / 2, 620)
    body = "\n  ".join([mark, agents_group, chaos_group])
    write_svg_set("aoc-logo-agents-of-chaos", width, height, body, "Agents of Chaos logo")


def write_logo_aoc(mark_path: str, box: tuple[float, float, float, float]) -> None:
    width, height = 700, 640
    center = width / 2
    mark = mark_group(mark_path, box, center, 64, 300)
    aoc = text_to_paths("AOC", 90, tracking=42)
    aoc_group = path_group(aoc.paths, center - aoc.width / 2, 520)
    body = "\n  ".join([mark, aoc_group])
    write_svg_set("aoc-logo-aoc", width, height, body, "AOC logo")


def write_mark(mark_path: str, box: tuple[float, float, float, float]) -> None:
    width = height = 512
    mark = mark_group(mark_path, box, width / 2, 54, 400)
    write_svg_set("aoc-mark", width, height, mark, "Agents of Chaos mark")


def main() -> None:
    mark_path, box = trace_mark_path()
    write_logo_agents(mark_path, box)
    write_logo_aoc(mark_path, box)
    write_mark(mark_path, box)
    for stem in ("aoc-logo-agents-of-chaos", "aoc-logo-aoc", "aoc-mark"):
        print(BRAND_DIR / f"{stem}.svg")
        for suffix in BACKGROUNDS:
            print(BRAND_DIR / f"{stem}-{suffix}.svg")


if __name__ == "__main__":
    main()
