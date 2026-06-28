from __future__ import annotations

from pathlib import Path
import os
import re

import numpy as np
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image, ImageFilter
from skimage import measure, morphology


ROOT = Path(__file__).resolve().parents[1]
SPECIMEN = ROOT / "public" / "brand" / "type-specimen-crop.png"
WORDMARK = ROOT / "public" / "brand" / "aoc-wordmark-reference.png"
OUT_DIR = ROOT / "public" / "fonts"
OUT_FONT = OUT_DIR / "AgentsSans.ttf"

UNITS_PER_EM = 1000
ASCENT = 840
DESCENT = -260
TRACE_TOLERANCE = float(os.environ.get("AGENTS_SANS_TRACE_TOLERANCE", "1.2"))
A_TRACE_TOLERANCE = float(os.environ.get("AGENTS_SANS_A_TRACE_TOLERANCE", "2.0"))
LOWERCASE_SCALE = float(os.environ.get("AGENTS_SANS_LOWERCASE_SCALE", "7.9"))
LOWER_XHEIGHT = 440
LOWER_ASCENDER = 620
LOWER_DOT_ASCENDER = 610
LOWER_T_ASCENDER = 600
LOWER_DESCENDER = -190
LOWER_BASELINE = 0


ROWS = [
    ("ABCDEFGHIJKLM", 35, 66),
    ("NOPQRSTUVWXYZ", 67, 98),
    ("abcdefghijklm", 150, 178),
    ("nopqrstuvwxyz", 180, 208),
    ("0123456789", 260, 292),
    ('!@#$%^&*()_-+=[]{}|;:"\',.<>', 340, 380),
]

ALIASES = {
    "–": "-",
    "—": "-",
    "−": "-",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "…": ".",
    "•": "*",
    "·": "*",
    "à": "a",
    "é": "e",
    "É": "E",
    "ü": "u",
    "←": "<",
    "→": ">",
    "↔": "-",
    "▸": ">",
    "▾": "v",
    "○": "o",
    "●": "o",
    "★": "*",
}


def glyph_name(ch: str) -> str:
    if ch == " ":
        return "space"
    if re.match(r"[A-Za-z0-9]", ch):
        return ch
    return f"uni{ord(ch):04X}"


def merge_close(groups: list[tuple[int, int]], gap: int = 2) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in groups:
        if merged and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def column_groups(mask: np.ndarray) -> list[tuple[int, int]]:
    cols = mask.sum(axis=0) > 0
    groups: list[tuple[int, int]] = []
    start: int | None = None
    for i, value in enumerate(cols):
        if value and start is None:
            start = i
        if start is not None and (not value or i == len(cols) - 1):
            end = i if not value else i + 1
            if end - start > 1:
                groups.append((start, end))
            start = None
    return merge_close(groups)


def make_empty_glyph():
    return TTGlyphPen(None).glyph()


def make_manual_glyph(
    contours: list[list[tuple[int, int]]],
    advance: int = 520,
) -> tuple[object, int]:
    pen = TTGlyphPen(None)
    for contour in contours:
        pen.moveTo(contour[0])
        for point in contour[1:]:
            pen.lineTo(point)
        pen.closePath()
    return pen.glyph(), advance


def chamfered_rect(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    corner: int = 18,
    clockwise: bool = True,
) -> list[tuple[int, int]]:
    points = [
        (x0 + corner, y0),
        (x0, y0 + corner),
        (x0, y1 - corner),
        (x0 + corner, y1),
        (x1 - corner, y1),
        (x1, y1 - corner),
        (x1, y0 + corner),
        (x1 - corner, y0),
    ]
    return points if clockwise else list(reversed(points))


def append_manual_contours(glyph: object, contours: list[list[tuple[int, int]]]) -> object:
    pen = TTGlyphPen(None)
    glyph.draw(pen, None)
    for contour in contours:
        pen.moveTo(contour[0])
        for point in contour[1:]:
            pen.lineTo(point)
        pen.closePath()
    combined = pen.glyph()
    recalc_bounds(combined)
    return combined


def manual_descender_glyph(ch: str) -> tuple[object, int]:
    if ch == "g":
        return make_manual_glyph(
            [
                [
                    (126, 20),
                    (76, 70),
                    (76, 390),
                    (126, 440),
                    (500, 440),
                    (550, 390),
                    (550, 70),
                    (500, 20),
                    (348, 20),
                    (348, -128),
                    (314, -165),
                    (236, -165),
                    (202, -128),
                    (202, 20),
                ],
                chamfered_rect(198, 118, 428, 332, 22, clockwise=False),
            ],
            641,
        )
    if ch == "j":
        return make_manual_glyph(
            [
                [(84, -142), (84, 410), (114, 440), (194, 440), (194, -142), (146, -190)],
                chamfered_rect(86, 520, 190, 610, 16, clockwise=True),
            ],
            320,
        )
    if ch == "p":
        return make_manual_glyph(
            [
                [
                    (76, -190),
                    (76, 410),
                    (106, 440),
                    (500, 440),
                    (550, 390),
                    (550, 70),
                    (500, 20),
                    (190, 20),
                    (190, -190),
                ],
                chamfered_rect(198, 118, 428, 332, 22, clockwise=False),
            ],
            633,
        )
    if ch == "q":
        return make_manual_glyph(
            [
                [
                    (550, -190),
                    (436, -190),
                    (436, 20),
                    (126, 20),
                    (76, 70),
                    (76, 390),
                    (126, 440),
                    (520, 440),
                    (550, 410),
                ],
                chamfered_rect(198, 118, 428, 332, 22, clockwise=False),
            ],
            633,
        )
    if ch == "y":
        return make_manual_glyph(
            [
                [
                    (76, 440),
                    (186, 440),
                    (186, 134),
                    (222, 92),
                    (392, 92),
                    (436, 134),
                    (436, 440),
                    (546, 440),
                    (546, -142),
                    (498, -190),
                    (252, -190),
                    (252, -102),
                    (426, -102),
                    (436, -62),
                    (436, 20),
                    (190, 20),
                    (116, 70),
                    (76, 150),
                ]
            ],
            633,
        )
    raise ValueError(f"No manual descender glyph for {ch!r}")


def recalc_bounds(glyph: object) -> None:
    coords = getattr(glyph, "coordinates", None)
    if not coords:
        return
    xs = [x for x, y in coords]
    ys = [y for x, y in coords]
    glyph.xMin = min(xs)
    glyph.xMax = max(xs)
    glyph.yMin = min(ys)
    glyph.yMax = max(ys)


def deepen_descender(glyph: object, target: int = -220, knee: int = 110) -> object:
    coords = getattr(glyph, "coordinates", None)
    if not coords:
        return glyph
    y_min = min(y for x, y in coords)
    if y_min >= knee:
        return glyph
    factor = (knee - target) / max(knee - y_min, 1)
    for index, (x, y) in enumerate(coords):
        if y < knee:
            coords[index] = (x, int(round(knee + (y - knee) * factor)))
    recalc_bounds(glyph)
    return glyph


def normalize_lowercase_glyph(ch: str, glyph: object) -> object:
    coords = getattr(glyph, "coordinates", None)
    if not coords:
        return glyph

    recalc_bounds(glyph)
    y_min = glyph.yMin
    y_max = glyph.yMax
    if y_max <= 0:
        return glyph

    if ch in "bdhklf":
        top = LOWER_ASCENDER
    elif ch in "ij":
        top = LOWER_DOT_ASCENDER
    elif ch == "t":
        top = LOWER_T_ASCENDER
    else:
        top = LOWER_XHEIGHT

    bottom = LOWER_DESCENDER if ch in "gjpqy" else LOWER_BASELINE
    positive_scale = top / max(y_max, 1)
    negative_scale = bottom / y_min if y_min < 0 and bottom < 0 else 0

    for index, (x, y) in enumerate(coords):
        if y >= 0:
            coords[index] = (x, int(round(y * positive_scale)))
        elif bottom < 0:
            coords[index] = (x, int(round(y * negative_scale)))
        else:
            coords[index] = (x, LOWER_BASELINE)

    recalc_bounds(glyph)
    return glyph


def refine_descender_shape(ch: str, glyph: object) -> object:
    coords = getattr(glyph, "coordinates", None)
    if not coords:
        return glyph
    if ch == "p":
        for index, (x, y) in enumerate(coords):
            if x <= 210 and y < -105:
                coords[index] = (x, LOWER_DESCENDER)
    elif ch == "q":
        for index, (x, y) in enumerate(coords):
            if x >= 420 and y < -105:
                coords[index] = (x, LOWER_DESCENDER)
    elif ch == "y":
        for index, (x, y) in enumerate(coords):
            if y < -145:
                coords[index] = (470 if x < 500 else 530, LOWER_DESCENDER)
            elif y < 0:
                coords[index] = (x, int(round(y * 0.86)))
    else:
        return glyph
    recalc_bounds(glyph)
    return glyph


def tune_text_glyph(ch: str, glyph: object, advance: int) -> tuple[object, int]:
    """Normalize small lowercase glyphs for paragraph use."""
    if ch in "ijl":
        advance = max(advance, 320)
    elif ch in "frt":
        advance = max(advance, 350)
    elif ch in "mw":
        advance = max(advance, 560)
    elif ch.islower():
        advance = max(advance, 410)
    if ch in "gjpqy":
        glyph = deepen_descender(glyph)
    glyph = normalize_lowercase_glyph(ch, glyph)
    glyph = refine_descender_shape(ch, glyph)
    return glyph, advance


def manual_punctuation_glyph(ch: str) -> tuple[object, int]:
    if ch == ".":
        return make_manual_glyph([[(62, 0), (150, 0), (150, 88), (62, 88)]], 230)
    if ch == ",":
        return make_manual_glyph(
            [
                [(62, 0), (150, 0), (150, 88), (62, 88)],
                [(106, -95), (168, 0), (112, 0), (50, -95)],
            ],
            230,
        )
    if ch == ":":
        return make_manual_glyph(
            [
                [(62, 0), (150, 0), (150, 88), (62, 88)],
                [(62, 292), (150, 292), (150, 380), (62, 380)],
            ],
            230,
        )
    if ch == ";":
        return make_manual_glyph(
            [
                [(62, 0), (150, 0), (150, 88), (62, 88)],
                [(106, -95), (168, 0), (112, 0), (50, -95)],
                [(62, 292), (150, 292), (150, 380), (62, 380)],
            ],
            230,
        )
    raise ValueError(f"No manual punctuation glyph for {ch!r}")


def manual_special_glyph(ch: str) -> tuple[object, int]:
    if ch == "/":
        return make_manual_glyph([[(120, 210), (170, 210), (350, 520), (300, 520)]], 440)
    if ch == "\\":
        return make_manual_glyph([[(285, 210), (335, 210), (155, 520), (105, 520)]], 440)
    if ch == "?":
        return make_manual_glyph(
            [
                [(110, 470), (150, 520), (350, 520), (400, 485), (400, 405), (335, 405), (335, 465), (175, 465), (150, 430)],
                [(335, 405), (400, 405), (400, 345), (285, 275), (250, 330)],
                [(230, 210), (315, 210), (315, 285), (230, 285)],
            ],
            500,
        )
    if ch == "`":
        return make_manual_glyph([[(210, 635), (285, 635), (345, 515), (280, 515)]], 430)
    if ch == "~":
        return make_manual_glyph(
            [
                [(95, 360), (150, 420), (235, 392), (310, 360), (365, 420), (430, 420), (365, 320), (285, 320), (210, 350), (150, 312)]
            ],
            500,
        )
    raise ValueError(f"No manual glyph for {ch!r}")


def manual_a_glyph() -> tuple[object, int]:
    wordmark = Image.open(WORDMARK).convert("RGBA")
    alpha = np.asarray(wordmark.getchannel("A"))
    top_line = alpha[:40, :] > 12
    groups = column_groups(top_line)
    if not groups:
        raise RuntimeError("Could not isolate A from wordmark asset")
    x1, x2 = groups[0]
    y_values, x_values = np.nonzero(top_line[:, x1:x2])
    y1 = max(0, int(y_values.min()) - 2)
    y2 = min(40, int(y_values.max()) + 3)
    crop = alpha[y1:y2, max(0, x1 - 2) : min(alpha.shape[1], x2 + 2)]
    mask_y, mask_x = np.nonzero(crop > 12)
    if len(mask_x) == 0:
        return trace_glyph(crop, 710, tolerance=2.2, smooth=1.25)

    center = (float(mask_x.min()) + float(mask_x.max())) / 2
    mirrored = crop.copy()
    for x in range(crop.shape[1]):
        if x <= center:
            continue
        source_x = int(round((center * 2) - x))
        if 0 <= source_x < crop.shape[1]:
            mirrored[:, x] = crop[:, source_x]

    bar_top = int(round(crop.shape[0] * 0.46))
    bar_bottom = int(round(crop.shape[0] * 0.78))
    bar_left = max(0, int(round(center)) - 3)
    mirrored[bar_top:bar_bottom, bar_left:] = np.maximum(
        mirrored[bar_top:bar_bottom, bar_left:],
        crop[bar_top:bar_bottom, bar_left:],
    )

    return trace_glyph(mirrored, 710, tolerance=2.2, smooth=1.25)


def trace_glyph(
    gray: np.ndarray,
    target_height: int,
    tolerance: float | None = None,
    smooth: float = 0,
    bottom: int = 0,
    threshold: int = 85,
) -> tuple[object, int]:
    upsample = 5
    source = Image.fromarray(gray.astype(np.uint8), mode="L")
    enlarged = source.resize(
        (gray.shape[1] * upsample, gray.shape[0] * upsample),
        Image.Resampling.LANCZOS,
    )
    if smooth:
        enlarged = enlarged.filter(ImageFilter.GaussianBlur(smooth))
    mask = np.asarray(enlarged) > threshold
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return make_empty_glyph(), 330

    pad = 4
    x1 = max(0, int(xs.min()) - pad)
    x2 = min(mask.shape[1], int(xs.max()) + pad + 1)
    y1 = max(0, int(ys.min()) - pad)
    y2 = min(mask.shape[0], int(ys.max()) + pad + 1)
    glyph_mask = mask[y1:y2, x1:x2]

    # Light cleanup preserves the segmented display style while avoiding pinholes
    # from the source PNG anti-aliasing.
    glyph_mask = morphology.binary_closing(glyph_mask, morphology.square(2))
    h, w = glyph_mask.shape
    scale = target_height / max(h, 1)
    left_bearing = 55
    pen = TTGlyphPen(None)
    padded = np.pad(glyph_mask.astype(float), 1)
    contours = measure.find_contours(padded, 0.5)
    for contour in contours:
        if len(contour) < 3:
            continue
        pts: list[tuple[int, int]] = []
        # The source specimen is a raster image. A low tolerance preserves the
        # PNG stair-steps, which makes diagonals look bitten out at hero sizes.
        # A higher tolerance recovers the intended angular strokes.
        contour = measure.approximate_polygon(contour, tolerance=tolerance or TRACE_TOLERANCE)
        for y, x in contour:
            fx = int(round(left_bearing + (x - 1) * scale))
            fy = int(round(bottom + (h - (y - 1)) * scale))
            if not pts or pts[-1] != (fx, fy):
                pts.append((fx, fy))
        if len(pts) < 3:
            continue
        pen.moveTo(pts[0])
        for point in pts[1:]:
            pen.lineTo(point)
        pen.closePath()

    advance = int(round(left_bearing * 2 + w * scale))
    return pen.glyph(), max(advance, 260)


def trace_row_glyph(
    gray: np.ndarray,
    target_row_height: int,
    tolerance: float | None = None,
    smooth: float = 0,
    threshold: int = 105,
    bottom: int = 0,
    left_bearing: int = 48,
) -> tuple[object, int]:
    upsample = 5
    source = Image.fromarray(gray.astype(np.uint8), mode="L")
    enlarged = source.resize(
        (gray.shape[1] * upsample, gray.shape[0] * upsample),
        Image.Resampling.LANCZOS,
    )
    if smooth:
        enlarged = enlarged.filter(ImageFilter.GaussianBlur(smooth))
    mask = np.asarray(enlarged) > threshold
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return make_empty_glyph(), 330

    pad = 4
    x1 = max(0, int(xs.min()) - pad)
    x2 = min(mask.shape[1], int(xs.max()) + pad + 1)
    glyph_mask = mask[:, x1:x2]
    glyph_mask = morphology.binary_closing(glyph_mask, morphology.square(2))
    h, w = glyph_mask.shape
    scale = target_row_height / max(h, 1)

    pen = TTGlyphPen(None)
    padded = np.pad(glyph_mask.astype(float), 1)
    contours = measure.find_contours(padded, 0.5)
    for contour in contours:
        if len(contour) < 3:
            continue
        pts: list[tuple[int, int]] = []
        contour = measure.approximate_polygon(contour, tolerance=tolerance or TRACE_TOLERANCE)
        for y, x in contour:
            fx = int(round(left_bearing + (x - 1) * scale))
            fy = int(round(bottom + (h - (y - 1)) * scale))
            if not pts or pts[-1] != (fx, fy):
                pts.append((fx, fy))
        if len(pts) < 3:
            continue
        pen.moveTo(pts[0])
        for point in pts[1:]:
            pen.lineTo(point)
        pen.closePath()

    advance = int(round(left_bearing * 2 + w * scale))
    return pen.glyph(), max(advance, 180)


def trace_scaled_glyph(
    gray: np.ndarray,
    scale: float,
    source_baseline: int,
    source_bottom: int,
    tolerance: float | None = None,
    smooth: float = 0,
    threshold: int = 105,
    left_bearing: int = 48,
) -> tuple[object, int]:
    upsample = 5
    source = Image.fromarray(gray.astype(np.uint8), mode="L")
    enlarged = source.resize(
        (gray.shape[1] * upsample, gray.shape[0] * upsample),
        Image.Resampling.LANCZOS,
    )
    if smooth:
        enlarged = enlarged.filter(ImageFilter.GaussianBlur(smooth))
    mask = np.asarray(enlarged) > threshold
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return make_empty_glyph(), 330

    pad = 4
    x1 = max(0, int(xs.min()) - pad)
    x2 = min(mask.shape[1], int(xs.max()) + pad + 1)
    y1 = max(0, int(ys.min()) - pad)
    y2 = min(mask.shape[0], int(ys.max()) + pad + 1)
    glyph_mask = mask[y1:y2, x1:x2]
    glyph_mask = morphology.binary_closing(glyph_mask, morphology.square(2))
    h, w = glyph_mask.shape
    baseline_px = source_baseline * upsample

    pen = TTGlyphPen(None)
    padded = np.pad(glyph_mask.astype(float), 1)
    contours = measure.find_contours(padded, 0.5)
    for contour in contours:
        if len(contour) < 3:
            continue
        pts: list[tuple[int, int]] = []
        contour = measure.approximate_polygon(contour, tolerance=tolerance or TRACE_TOLERANCE)
        for y, x in contour:
            fx = int(round(left_bearing + (x - 1) * scale))
            source_y = y1 + (y - 1)
            fy = int(round((baseline_px - source_y) * scale))
            if not pts or pts[-1] != (fx, fy):
                pts.append((fx, fy))
        if len(pts) < 3:
            continue
        pen.moveTo(pts[0])
        for point in pts[1:]:
            pen.lineTo(point)
        pen.closePath()

    advance = int(round(left_bearing * 2 + w * scale))
    return pen.glyph(), max(advance, 180)


def main() -> None:
    img = Image.open(SPECIMEN).convert("L")
    arr = np.asarray(img)
    glyphs = {".notdef": make_empty_glyph(), "space": make_empty_glyph()}
    metrics = {".notdef": (520, 0), "space": (330, 0)}
    cmap = {32: "space"}
    order = [".notdef", "space"]

    for chars, y1, y2 in ROWS:
        row = arr[y1:y2, :]
        row_mask = row > 85
        groups = column_groups(row_mask)
        lowercase_baseline = 26 if chars == "nopqrstuvwxyz" else 27
        if len(groups) != len(chars):
            raise RuntimeError(f"Expected {len(chars)} glyphs for {chars!r}, found {len(groups)}")
        for ch, (x1, x2) in zip(chars, groups):
            crop = row[:, max(0, x1 - 3) : min(row.shape[1], x2 + 3)]
            if ch.islower() and ch in "tw":
                crop = crop.copy()
                crop[:10, :] = 0
            crop_mask = crop > 85
            crop_ys = np.nonzero(crop_mask)[0]
            source_bottom = int(crop_ys.max()) if len(crop_ys) else y2 - y1
            if ch == "A":
                glyph, advance = manual_a_glyph()
            elif ch in "gjpqy":
                glyph, advance = manual_descender_glyph(ch)
            elif ch.islower():
                glyph, advance = trace_scaled_glyph(
                    crop,
                    scale=LOWERCASE_SCALE,
                    source_baseline=lowercase_baseline,
                    source_bottom=source_bottom,
                    tolerance=1.15,
                    threshold=120,
                )
                glyph, advance = tune_text_glyph(ch, glyph, advance)
            elif ch in ".,;:":
                glyph, advance = manual_punctuation_glyph(ch)
            elif ch in '!@#$%^&*()_-+=[]{}|;:"\',.<>':
                glyph, advance = trace_scaled_glyph(
                    crop,
                    scale=4.8,
                    source_baseline=33,
                    source_bottom=source_bottom,
                    tolerance=1.0,
                    threshold=120,
                    left_bearing=36,
                )
            else:
                target_height = 710 if ch.isupper() or ch.isdigit() else 540
                glyph, advance = trace_glyph(crop, target_height)
            name = glyph_name(ch)
            glyphs[name] = glyph
            metrics[name] = (advance, 0)
            cmap[ord(ch)] = name
            order.append(name)

    for ch in "?/\\`~":
        name = glyph_name(ch)
        glyph, advance = manual_special_glyph(ch)
        glyphs[name] = glyph
        metrics[name] = (advance, 0)
        cmap[ord(ch)] = name
        order.append(name)

    for char, source in ALIASES.items():
        source_name = glyph_name(source)
        if source_name in glyphs:
            cmap[ord(char)] = source_name

    fb = FontBuilder(UNITS_PER_EM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    fb.setupOS2(
        sTypoAscender=ASCENT,
        sTypoDescender=DESCENT,
        usWinAscent=ASCENT,
        usWinDescent=abs(DESCENT),
        sxHeight=460,
        sCapHeight=710,
    )
    fb.setupNameTable(
        {
            "familyName": "Agents Sans",
            "styleName": "Regular",
            "uniqueFontIdentifier": "Agents Sans Regular traced from identity specimen",
            "fullName": "Agents Sans Regular",
            "psName": "AgentsSans-Regular",
            "version": "Version 0.1",
        }
    )
    fb.setupPost()
    OUT_DIR.mkdir(exist_ok=True)
    fb.save(OUT_FONT)
    print(OUT_FONT)


if __name__ == "__main__":
    main()
