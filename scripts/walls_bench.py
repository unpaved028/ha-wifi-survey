"""Prüfstand der Wanderkennung: erzeugte Grundrisse in fünf Zeichenstilen (schraffiert, schwarz, grau, hellgrau
mit Rand, nur Umriss), je ohne und mit Scan-Rauschen. Misst, wie viel der echten Wandlänge gefunden wird und wie viel
der erkannten Länge auf echten Wänden liegt.

    .venv/bin/python scripts/walls_bench.py [debug]     # debug: Bilder nach /tmp/ws-styles/

Nach Änderungen an walls.py zusätzlich echte Pläne prüfen.
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from wifi_survey.walls import detect

PPM = 80   # px je m, etwa wie ein eingescannter Bauplan
# Wände (Mittellinie, Dicke in px): Außen 36,5 cm, innen 24 und 11,5 cm, mit Türöffnungen
def layout():
    o = 150
    W, H = 16 * PPM, 11 * PPM
    t_ext, t_24, t_11 = 29, 19, 9
    walls = []
    # Außenwände mit Fensteröffnungen (Lücken) oben und unten
    def hwall(y, x0, x1, t, gaps=()):
        xs = [x0] + [g for gp in gaps for g in gp] + [x1]
        for a, b in zip(xs[::2], xs[1::2]):
            walls.append(((a, y), (b, y), t))
    def vwall(x, y0, y1, t, gaps=()):
        ys = [y0] + [g for gp in gaps for g in gp] + [y1]
        for a, b in zip(ys[::2], ys[1::2]):
            walls.append(((x, a), (x, b), t))
    hwall(o, o - t_ext // 2, o + W + t_ext // 2, t_ext, gaps=[(o + 200, o + 320), (o + 700, o + 860)])
    hwall(o + H, o - t_ext // 2, o + W + t_ext // 2, t_ext, gaps=[(o + 300, o + 380), (o + 900, o + 1060)])
    vwall(o, o, o + H, t_ext, gaps=[(o + 300, o + 420)])
    vwall(o + W, o, o + H, t_ext)
    vwall(o + 560, o + t_ext // 2, o + H - t_ext // 2, t_24, gaps=[(o + 400, o + 480)])
    hwall(o + 460, o + t_ext // 2, o + 560 - t_24 // 2, t_11, gaps=[(o + 250, o + 320)])
    hwall(o + 520, o + 560 + t_24 // 2, o + W - t_ext // 2, t_11, gaps=[(o + 800, o + 870)])
    vwall(o + 980, o + 520 + t_11 // 2, o + H - t_ext // 2, t_11, gaps=[(o + 640, o + 710)])
    size = (o * 2 + H + 120, o * 2 + W)
    return walls, size, o, W, H

def rect_of(a, b, t):
    (x0, y0), (x1, y1) = a, b
    if y0 == y1:
        return (min(x0, x1), y0 - t / 2, max(x0, x1), y0 + t / 2)
    return (x0 - t / 2, min(y0, y1), x0 + t / 2, max(y0, y1))

def draw(style, noise=False):
    walls, (h, w), o, W, H = layout()
    img = np.full((h, w), 255, np.uint8)
    hatch = np.full_like(img, 255)
    for k in range(-h, w, 8):
        cv2.line(hatch, (k, 0), (k + h, h), 0, 2)
    for a, b, t in walls:
        x0, y0, x1, y1 = [round(v) for v in rect_of(a, b, t)]
        if style == "schraffiert":
            m = np.zeros_like(img); cv2.rectangle(m, (x0, y0), (x1, y1), 255, -1)
            img[(m > 0) & (hatch == 0)] = 0
            cv2.rectangle(img, (x0, y0), (x1, y1), 0, 2)
        elif style == "schwarz":
            cv2.rectangle(img, (x0, y0), (x1, y1), 0, -1)
        elif style == "grau":
            cv2.rectangle(img, (x0, y0), (x1, y1), 110, -1)
        elif style == "hellgrau":
            cv2.rectangle(img, (x0, y0), (x1, y1), 195, -1)
            cv2.rectangle(img, (x0, y0), (x1, y1), 0, 1)
        elif style == "umriss":
            cv2.rectangle(img, (x0, y0), (x1, y1), 0, 2)
    # Fenster in den Lücken der Außenwand: zwei dünne Linien (Glas)
    for (gx0, gx1, gy) in [(o + 200, o + 320, o), (o + 700, o + 860, o), (o + 300, o + 380, o + H), (o + 900, o + 1060, o + H)]:
        for dy in (-5, 5):
            cv2.line(img, (gx0, gy + dy), (gx1, gy + dy), 0, 1)
    # Türbögen
    for (cx, cy, r, a0) in [(o + 560, o + 400, 80, 90), (o + 250, o + 460, 70, 0), (o + 800 + 560, o + 520, 70, 0)]:
        cv2.ellipse(img, (cx, cy), (r, r), 0, a0, a0 + 90, 0, 1)
    # Text, Bemaßung, Möbel
    for (txt, x, y) in [("WOHNEN 32,66", o + 120, o + 250), ("KUECHE 9,8", o + 700, o + 300), ("BAD 6,1", o + 1050, o + 700),
                        ("SCHLAFEN 14,2", o + 150, o + 700)]:
        cv2.putText(img, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    cv2.line(img, (o, o + H + 70), (o + W, o + H + 70), 0, 1)
    for x in range(o, o + W + 1, 160):
        cv2.line(img, (x - 6, o + H + 76), (x + 6, o + H + 64), 0, 2)
        cv2.putText(img, "2,00", (x + 40, o + H + 62), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)
    for y in (o - 90, o - 62):                                         # doppelte Maßkette mit Zahlen
        cv2.line(img, (o, y), (o + W, y), 0, 1)
    for x in range(o, o + W + 1, 200):
        cv2.line(img, (x, o - 96), (x, o - 56), 0, 1)
        cv2.putText(img, "2,50", (x + 70, o - 68), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 0, 1)
    cv2.rectangle(img, (o + 700, o + 120), (o + 900, o + 220), 0, 2)     # Tisch
    cv2.circle(img, (o + 300, o + 150), 30, 0, 2)
    cv2.rectangle(img, (o + 1100, o + 600), (o + 1200, o + 800), 0, 2)  # Wanne
    if noise:
        img = cv2.GaussianBlur(img, (3, 3), 0)
        rng = np.random.default_rng(1)
        img = np.clip(img.astype(np.int16) + rng.normal(0, 18, img.shape).astype(np.int16), 0, 255).astype(np.uint8)
    return img, walls

def score(segs, walls):
    gt = [rect_of(a, b, t) for a, b, t in walls]
    def in_gt(x, y, pad):
        return any(x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad for x0, y0, x1, y1 in gt)
    def covered(x, y):
        for s in segs:
            ax, ay = s.a; bx, by = s.b
            L = math.dist(s.a, s.b) or 1
            t = max(0, min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L ** 2))
            px, py = ax + t * (bx - ax), ay + t * (by - ay)
            if math.dist((x, y), (px, py)) <= s.thickness_px / 2 + 4:
                return True
        return False
    tot = hit = 0
    for a, b, t in walls:
        n = max(2, int(math.dist(a, b) / 5))
        for i in range(n + 1):
            x = a[0] + (b[0] - a[0]) * i / n; y = a[1] + (b[1] - a[1]) * i / n
            tot += 1; hit += covered(x, y)
    dtot = dok = 0
    for s in segs:
        n = max(2, int(s.length() / 5))
        for i in range(n + 1):
            x = s.a[0] + (s.b[0] - s.a[0]) * i / n; y = s.a[1] + (s.b[1] - s.a[1]) * i / n
            dtot += 1; dok += in_gt(x, y, 5)
    return hit / tot, (dok / dtot if dtot else 0.0)

if __name__ == "__main__":
    for style in ("schraffiert", "schwarz", "grau", "hellgrau", "umriss"):
        for noise in (False, True):
            img, walls = draw(style, noise)
            res = detect(img)
            rec, prec = score(res.segments, walls)
            print(f"{style:12s} {'Rauschen' if noise else '        '}  Wände {len(res.segments):3d}  gefunden {rec*100:5.1f} %  richtig {prec*100:5.1f} %  Schraffur {res.hatch_direction}")
            if len(sys.argv) > 1:
                from wifi_survey.walls import render_debug
                Path("/tmp/ws-styles").mkdir(exist_ok=True)
                cv2.imwrite(f"/tmp/ws-styles/{style}{'-n' if noise else ''}.png", render_debug(img, res))
