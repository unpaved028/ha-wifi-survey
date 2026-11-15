import cv2
import numpy as np

from wifi_survey.walls import detect


def hatched_plan(h=600, w=800):
    """Künstlicher Grundriss: schraffierte Wände wie im Scan, dazu Bemaßung und Text als Störung."""
    img = np.full((h, w), 255, np.uint8)
    hatch = np.full_like(img, 255)
    for k in range(-h, w, 8):
        cv2.line(hatch, (k, 0), (k + h, h), 0, 2)

    def wall(x0, y0, x1, y1):
        cv2.rectangle(img, (x0, y0), (x1, y1), 0, 2)
        mask = np.zeros_like(img)
        cv2.rectangle(mask, (x0, y0), (x1, y1), 255, -1)
        img[(mask > 0) & (hatch == 0)] = 0

    wall(100, 100, 699, 129)   # Außenwand oben, 30 px dick
    wall(100, 100, 129, 499)   # Außenwand links, 30 px
    wall(400, 130, 419, 499)   # Innenwand, 20 px
    cv2.line(img, (100, 560), (700, 560), 0, 1)                      # Maßlinie
    for x in range(100, 701, 100):
        cv2.line(img, (x - 6, 566), (x + 6, 554), 0, 2)              # Maßstriche (diagonal!)
    cv2.putText(img, "WOHNEN 32.66", (180, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    cv2.rectangle(img, (480, 250), (600, 330), 0, 2)                 # Möbel
    return img


def find(segments, pred):
    return [s for s in segments if pred(s)]


def test_detects_walls_with_position_and_thickness():
    res = detect(hatched_plan())
    segs = res.segments
    top = find(segs, lambda s: s.angle == 0 and abs(s.a[1] - 114.5) < 4 and s.length() > 500)
    left = find(segs, lambda s: s.angle == 90 and abs(s.a[0] - 114.5) < 4 and s.length() > 300)
    inner = find(segs, lambda s: s.angle == 90 and abs(s.a[0] - 409.5) < 4 and s.length() > 300)
    assert top, segs
    assert left, segs
    assert inner, segs
    assert abs(top[0].thickness_px - 30) <= 3
    assert abs(left[0].thickness_px - 30) <= 3
    assert abs(inner[0].thickness_px - 20) <= 3
    assert min(top[0].confidence, left[0].confidence, inner[0].confidence) >= 0.9
    # Wandenden liegen an den gezeichneten Enden
    xs = sorted([top[0].a[0], top[0].b[0]])
    assert abs(xs[0] - 100) <= 4 and abs(xs[1] - 700) <= 4


def test_ignores_dimension_lines_text_and_furniture():
    res = detect(hatched_plan())
    for s in res.segments:
        cy = (s.a[1] + s.b[1]) / 2
        cx = (s.a[0] + s.b[0]) / 2
        assert not (540 < cy < 580), f"Maßlinie als Wand erkannt: {s}"
        assert not (470 < cx < 610 and 240 < cy < 340), f"Möbel als Wand erkannt: {s}"
        # Fette Schrift darf auftauchen, muss aber als unsicher markiert sein
        if 170 < cx < 380 and 300 < cy < 340:
            assert s.confidence < 0.75, f"Text als sichere Wand erkannt: {s}"


def test_empty_image_gives_no_walls():
    res = detect(np.full((300, 300), 255, np.uint8))
    assert res.segments == []


def styled_plan(style, h=600, w=800):
    """Wie hatched_plan, aber Wände hellgrau gefüllt mit dünnem Rand oder nur als Umriss (zwei Linien)."""
    img = np.full((h, w), 255, np.uint8)
    for x0, y0, x1, y1 in ((100, 100, 699, 129), (100, 100, 129, 499), (400, 130, 419, 499)):
        if style == "light":
            cv2.rectangle(img, (x0, y0), (x1, y1), 195, -1)
            cv2.rectangle(img, (x0, y0), (x1, y1), 0, 1)
        else:
            cv2.rectangle(img, (x0, y0), (x1, y1), 0, 2)
    cv2.line(img, (100, 560), (700, 560), 0, 1)
    cv2.putText(img, "WOHNEN 32.66", (180, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    cv2.rectangle(img, (480, 250), (600, 330), 0, 2)
    return img


def test_detects_light_gray_and_outline_walls():
    for style in ("light", "outline"):
        res = detect(styled_plan(style))
        segs = res.segments
        top = find(segs, lambda s: s.angle == 0 and abs(s.a[1] - 114.5) < 5 and s.length() > 500)
        inner = find(segs, lambda s: s.angle == 90 and abs(s.a[0] - 409.5) < 5 and s.length() > 300)
        assert top and inner, (style, segs)
        assert abs(top[0].thickness_px - 30) <= 4 and abs(inner[0].thickness_px - 20) <= 4, (style, top, inner)
        assert (res.hatch_direction == "Umriss") == (style == "outline")
    # schraffierter Plan bleibt beim gewohnten Weg, auch mit erzwungenem Stil „gefüllt“
    assert detect(hatched_plan()).hatch_direction != "Umriss"
    from wifi_survey.walls import DetectParams
    assert detect(styled_plan("outline"), DetectParams(style="filled")).hatch_direction != "Umriss"
