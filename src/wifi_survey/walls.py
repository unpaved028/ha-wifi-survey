"""Halbautomatische Wanderkennung in eingescannten Grundrissen.

Ablauf (siehe docs/entscheidungen/0003-plan-editor.md):
1. Wandmaske: Schraffur verstärken (Öffnen mit diagonalem Linienkern in der dominanten
   Schraffurrichtung), Schraffurlinien zu Flächen schließen, dünne Linien (Bemaßung, Text,
   Möbel) durch Öffnen entfernen, kleine Reste verwerfen, angrenzende Umrisslinien ergänzen.
   Dazu hell gefüllte Wände (deutlich dunkler als das Papier). Pläne, deren Wände nur als
   Umriss gezeichnet sind (Stil „outline“, „auto“ erkennt sie): schmale, lange, leere weiße
   Flächen zwischen Linien samt den Linien.
2. Richtungsweise Zerlegung: Für 0°, 90°, 45° und 135° wird die Maske so gedreht, dass die
   Richtung waagrecht liegt, und mit einem waagrechten Linienkern geöffnet. Übrig bleiben
   Wandläufe, die in dieser Richtung länger sind als jede Wand dick ist. Jeder Lauf wird zu
   einem Rechteck: Mittellinie (Ausgleichsgerade) plus Dicke (Median der Querschnitte).
   Ändert sich die Dicke entlang eines Laufs deutlich, wird er geteilt.
3. Ergebnis: Wände als Rechtecke von Wandende zu Wandende (Ecken überlappen), so wie sie
   im Plan gezeichnet sind.

Alle Koordinaten sind Pixel des Stockwerkbilds (x nach rechts, y nach unten).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

ANGLES = (0, 90, 45, 135)


@dataclass
class DetectParams:
    ink_threshold: int = 160      # Grauwert, unter dem ein Pixel als Tinte zählt
    hatch_len: int = 6            # Mindestlänge diagonaler Schraffurstriche (px); kurz genug für gestrichelte Schraffur
    close_size: int = 11          # schließt Lücken zwischen Schraffurlinien (> Linienabstand)
    open_size: int = 7            # entfernt Linien dünner als das (Bemaßung, Text, Möbel)
    min_area: int = 300           # kleinere Wandflächen werden verworfen (px²)
    run_factor: float = 1.25      # Mindestlauflänge = run_factor × größte Wanddicke
    diag_run_factor: float = 1.7  # dasselbe für 45°/135° (Querschnitt gerader Wände ist dort länger)
    min_thickness: float = 5.0    # dünnere Läufe verwerfen (px)
    split_change: float = 0.3     # relativer Dickensprung, ab dem ein Lauf geteilt wird
    min_piece: int = 12           # Mindestlänge eines Teilstücks nach dem Teilen (px)
    min_residual_area: int = 150  # Reste kleiner als das ignorieren (px²)
    min_residual_fill: float = 0.6  # Reste müssen ihr umschließendes Rechteck so weit füllen
    touch_gap: float = 3.0        # Abstand (px), bis zu dem zwei Wände als verbunden gelten
    isolated_len_factor: float = 3.0  # isolierte Stücke kürzer als das × größte Dicke sind verdächtig
    isolated_penalty: float = 0.6     # Faktor auf die Sicherheit für verdächtige Stücke
    clean: bool = True            # automatische Nachbearbeitung (cleanup.py) anwenden
    # Zeichenstil der Wände: "auto" (erkennen), "filled" (schraffiert oder gefüllt), "outline" (nur Umrisslinien)
    style: str = "auto"
    tone_margin: int = 30         # helle Füllungen: alles, was so viel dunkler ist als das Papier, zählt als Fläche
    outline_max_half: float = 30.0  # Umriss-Wände: halbe Dicke höchstens (px), also Wände bis 60 px
    outline_min_area: int = 200     # kleinere weiße Flächen (Buchstaben, Symbole) zählen nicht
    outline_elongation: float = 20.0  # Fläche ≥ das × (halbe Dicke)², also lang und schmal (Stufen, Schränke nicht)
    outline_max_holes: float = 0.03   # mehr Tinte darin (Zahlen einer Maßkette, Text): keine Wand
    # „auto“ wählt Umriss nur, wenn gefüllte Flächen weniger als das vom Bild bedecken. Erzeugte Testpläne:
    # Umriss 0,2–0,5 %, gefüllt oder schraffiert etwa 7 %; Dachgeschoss im Testhaus (wenige Wände) 2 %
    outline_auto_max: float = 0.01


@dataclass
class Segment:
    a: tuple[float, float]
    b: tuple[float, float]
    thickness_px: float
    angle: int = 0                # Richtungsklasse 0/45/90/135
    fill: float = 1.0             # Anteil der Maske im Rechteck (0..1)
    confidence: float = 1.0       # Sicherheit (0..1): fill, abgewertet für kurze isolierte Stücke

    def length(self) -> float:
        return math.dist(self.a, self.b)


@dataclass
class DetectResult:
    segments: list[Segment]
    mask: np.ndarray = field(repr=False)
    hatch_direction: str = ""
    stats: dict = field(default_factory=dict)


def _diag_kernel(length: int, anti: bool) -> np.ndarray:
    k = np.zeros((length, length), np.uint8)
    for i in range(length):
        k[i, length - 1 - i if anti else i] = 1
    return k


def _rect(n: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_RECT, (n, n))


def _light_fill(gray: np.ndarray, p: DetectParams) -> np.ndarray:
    """Hell gefüllte Wandflächen (z. B. Grau mit dünnem Rand, wie in Exposés): Flächen, die deutlich dunkler sind als
    das Papier und mindestens open_size dick. Dünne Linien, Text und die Kanten eines Scans fallen beim Öffnen weg."""
    smooth = cv2.medianBlur(gray, 5)          # Rauschen eines Scans, sonst zerfällt die Füllung in Stücke
    paper = float(np.percentile(smooth, 90))
    tone = (smooth < paper - p.tone_margin).astype(np.uint8)
    return cv2.morphologyEx(tone, cv2.MORPH_OPEN, _rect(p.open_size))


def _outline_fill(ink: np.ndarray, p: DetectParams) -> np.ndarray:
    """Wände, die nur als Umriss gezeichnet sind: schmale, lange weiße Flächen zwischen Linien, mit den Linien.

    Räume sind zu breit, Buchstaben und Symbole zu klein, Stufen und Schränke nicht lang genug."""
    free = (ink == 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    dt = cv2.distanceTransform(free, cv2.DIST_L2, 3)
    half = np.zeros(n)
    np.maximum.at(half, lab.ravel(), dt.ravel())
    area = stats[:, cv2.CC_STAT_AREA].astype(float)
    ok = (half <= p.outline_max_half) & (area >= p.outline_min_area) & (area >= p.outline_elongation * half ** 2)
    ok[0] = False    # Label 0: Tinte
    fill = ok[lab].astype(np.uint8)
    # Flächen mit Tinte darin (Zahlen zwischen den Linien einer Maßkette, Beschriftung) sind keine Wände
    cs, _ = cv2.findContours(fill, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    solid = np.zeros_like(fill)
    cv2.drawContours(solid, cs, -1, 1, -1)
    n2, lab2 = cv2.connectedComponents(solid, connectivity=8)
    inked = np.bincount(lab2[(solid > 0) & (fill == 0)], minlength=n2)
    total = np.bincount(lab2.ravel(), minlength=n2)
    bad = inked > p.outline_max_holes * total
    bad[0] = False
    fill[bad[lab2]] = 0
    return (fill | (ink & cv2.dilate(fill, _rect(5)))).astype(np.uint8)


def wall_mask(gray: np.ndarray, p: DetectParams) -> tuple[np.ndarray, str]:
    """Binäre Maske (0/1) der Wandflächen: schraffiert, massiv, hell gefüllt oder (Stil „outline“) nur als Umriss.

    Zweiter Rückgabewert: Schraffurrichtung („\\“, „/“) bzw. „Umriss“, wenn die Wände als Umriss erkannt wurden."""
    ink = (gray < p.ink_threshold).astype(np.uint8)
    if p.style != "outline":
        mask, direction = _filled_mask(gray, ink, p)
        if p.style == "filled":
            return mask, direction
    if p.style == "auto" and mask.sum() >= p.outline_auto_max * mask.size:
        return mask, direction      # es gibt gefüllte Wände: kein Umriss-Plan
    outline = _outline_fill(ink, p)
    if p.style == "outline" or outline.sum() > 2 * max(int(mask.sum()), 1):
        # Umriss-Plan: gefüllte Flächen gibt es kaum, aber viele schmale Flächen zwischen Linien
        out = cv2.morphologyEx(outline, cv2.MORPH_CLOSE, _rect(5))
        return out, "Umriss"
    return mask, direction


def _filled_mask(gray: np.ndarray, ink: np.ndarray, p: DetectParams) -> tuple[np.ndarray, str]:
    """Schraffierte und gefüllte Wandflächen (bisheriger Weg, plus helle Füllungen)."""
    d_back = cv2.morphologyEx(ink, cv2.MORPH_OPEN, _diag_kernel(p.hatch_len, anti=False))  # "\\"
    d_fwd = cv2.morphologyEx(ink, cv2.MORPH_OPEN, _diag_kernel(p.hatch_len, anti=True))    # "/"
    hatch, direction = (d_back, "\\") if d_back.sum() >= d_fwd.sum() else (d_fwd, "/")

    closed = cv2.morphologyEx(hatch, cv2.MORPH_CLOSE, _rect(p.close_size))
    opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, _rect(p.open_size))

    n, lab, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= p.min_area
    mask = keep[lab].astype(np.uint8)

    # hell gefüllte Wände (dunkle Füllungen deckt die Schraffur-Erkennung schon ab)
    light = _light_fill(gray, p)
    if light.any():
        n, lab, stats, _ = cv2.connectedComponentsWithStats(light, connectivity=8)
        keep = np.zeros(n, bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= p.min_area
        mask = (mask | keep[lab]).astype(np.uint8)

    # Umrisslinien direkt an der Wandfläche dazunehmen, kleine Löcher schließen
    mask = (mask | (ink & cv2.dilate(mask, _rect(5)))).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _rect(5))
    return mask, direction


def _max_thickness(mask: np.ndarray) -> float:
    """Schätzt die größte vorkommende Wanddicke aus der Distanztransformation.

    Gemessen wird auf dem Skelett (Wandmitte), damit Ecken und Kreuzungen das Ergebnis
    nicht nach oben ziehen.
    """
    dt = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    skel = cv2.ximgproc.thinning(mask * 255, thinningType=cv2.ximgproc.THINNING_ZHANGSUEN) > 0
    vals = dt[skel]
    if vals.size == 0:
        return 0.0
    return 2.0 * float(np.percentile(vals, 95))


def _residual_segments(mask: np.ndarray, covered: np.ndarray, p: DetectParams) -> list[Segment]:
    """Kurze Wandstücke (Pfeiler, Stummel), die kein Richtungslauf erfasst hat.

    Rest der Maske ohne bereits erkannte Rechtecke; rechteckige Reste werden per
    kleinstem umschließendem Rechteck zu Segmenten.
    """
    rest = (mask & (1 - cv2.dilate(covered, _rect(5)))).astype(np.uint8)
    rest = cv2.morphologyEx(rest, cv2.MORPH_OPEN, _rect(5))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(rest, connectivity=8)
    out = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < p.min_residual_area:
            continue
        ys, xs = np.nonzero(lab == i)
        pts = np.stack([xs, ys], axis=1).astype(np.float32)
        (cx, cy), (w, h), ang = cv2.minAreaRect(pts)
        w, h = w + 1.0, h + 1.0  # Pixelmitten -> Kanten
        fill = area / max(w * h, 1.0)
        if fill < p.min_residual_fill:
            continue
        long_side, short_side = (w, h) if w >= h else (h, w)
        if short_side < p.min_thickness or long_side < 1.2 * short_side:
            continue
        theta = math.radians(ang if w >= h else ang + 90)
        ux, uy = math.cos(theta), math.sin(theta)
        snapped = _snap_direction(ux, uy)
        if snapped is not None:
            ux, uy, cls = snapped
        else:
            cls = round(math.degrees(math.atan2(uy, ux)) % 180)
        half = long_side / 2
        out.append(Segment((round(cx - ux * half, 1), round(cy - uy * half, 1)),
                           (round(cx + ux * half, 1), round(cy + uy * half, 1)),
                           round(short_side, 1), cls, round(min(fill, 1.0), 2)))
    return out


def _snap_direction(ux: float, uy: float, tol_deg: float = 6.0):
    ang = math.degrees(math.atan2(uy, ux)) % 180
    for target in (0, 45, 90, 135, 180):
        if abs(ang - target) <= tol_deg:
            t = math.radians(target % 180)
            return math.cos(t), math.sin(t), target % 180
    return None


def _rotate(img: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray]:
    """Dreht so, dass Linien unter `angle` (Grad, y nach unten) waagrecht liegen.

    Gibt das gedrehte Bild und die inverse 2x3-Matrix (gedreht -> original) zurück.
    """
    h, w = img.shape
    if angle == 0:
        return img, np.array([[1, 0, 0], [0, 1, 0]], np.float64)
    if angle == 90:
        # Transponieren: (x, y) -> (y, x); senkrechte Linien werden waagrecht
        return np.ascontiguousarray(img.T), np.array([[0, 1, 0], [1, 0, 0]], np.float64)
    c = (w / 2.0, h / 2.0)
    m = cv2.getRotationMatrix2D(c, angle, 1.0)  # positiver Winkel = gegen den Uhrzeigersinn im Bild
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = math.ceil(h * sin + w * cos), math.ceil(h * cos + w * sin)
    m[0, 2] += nw / 2.0 - c[0]
    m[1, 2] += nh / 2.0 - c[1]
    rot = cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_NEAREST, borderValue=0)
    return rot, cv2.invertAffineTransform(m)


def _runs_to_segments(run_mask: np.ndarray, src_mask: np.ndarray, inv: np.ndarray,
                      angle: int, min_len: int, p: DetectParams) -> list[Segment]:
    """Wandläufe (waagrecht im gedrehten Bild) zu Segmenten im Originalbild."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(run_mask, connectivity=4)
    out: list[Segment] = []
    for i in range(1, n):
        x, y, w, h, _a = stats[i]
        if w < min_len:
            continue
        comp = lab[y:y + h, x:x + w] == i
        cols = comp.any(axis=0)
        top = np.argmax(comp, axis=0).astype(np.float64)
        bottom = (h - 1 - np.argmax(comp[::-1], axis=0)).astype(np.float64)
        thick = np.where(cols, bottom - top + 1, 0.0)
        center = np.where(cols, (top + bottom) / 2.0, np.nan)

        # Lauf an deutlichen Dickensprüngen teilen
        smooth = cv2.medianBlur(np.clip(thick, 0, 255).astype(np.uint8).reshape(1, -1), 5).ravel().astype(float)
        pieces, start = [], 0
        for k in range(1, w):
            ref = np.median(smooth[start:k])
            if ref > 0 and abs(smooth[k] - ref) > max(3.0, p.split_change * ref) and k - start >= p.min_piece:
                # nur teilen, wenn der neue Wert eine Weile anhält
                ahead = smooth[k:k + p.min_piece]
                if len(ahead) >= p.min_piece and np.all(np.abs(ahead - ref) > max(3.0, p.split_change * ref)):
                    pieces.append((start, k))
                    start = k
        pieces.append((start, w))

        for s, e in pieces:
            if e - s < p.min_piece:
                continue
            seg_thick = float(np.median(thick[s:e][cols[s:e]])) if cols[s:e].any() else 0.0
            if seg_thick < p.min_thickness:
                continue
            xs = np.arange(s, e)[cols[s:e]]
            cy = center[s:e][cols[s:e]]
            if len(xs) >= 2:
                slope, inter = np.polyfit(xs, cy, 1)
                if abs(slope) > 0.05:  # kein sauberer Lauf in dieser Richtung
                    slope, inter = 0.0, float(np.median(cy))
            else:
                slope, inter = 0.0, float(cy.mean())
            x0, x1 = float(s), float(e)  # e ist exklusiv: Ende an der Pixelkante
            y0, y1 = inter + slope * x0, inter + slope * x1
            # Pixelmitte -> Kantenmaß: Läufe enden an den Pixelkanten
            pa_r = (x + x0 - 0.5, y + y0)
            pb_r = (x + x1 - 0.5, y + y1)
            pa = inv @ np.array([pa_r[0], pa_r[1], 1.0])
            pb = inv @ np.array([pb_r[0], pb_r[1], 1.0])
            block = comp[:, s:e]
            fill = float(block.sum()) / max(1.0, (e - s) * seg_thick)
            out.append(Segment((round(float(pa[0]), 1), round(float(pa[1]), 1)),
                               (round(float(pb[0]), 1), round(float(pb[1]), 1)),
                               round(seg_thick, 1), angle, round(min(fill, 1.0), 2)))
    return out


def segments_from_mask(mask: np.ndarray, p: DetectParams) -> tuple[list[Segment], dict]:
    t_max = max(_max_thickness(mask), 8.0)
    claimed = np.zeros_like(mask)
    segments: list[Segment] = []
    for angle in ANGLES:
        diag = angle in (45, 135)
        min_len = math.ceil((p.diag_run_factor if diag else p.run_factor) * t_max)
        src = mask if not diag else (mask & (1 - cv2.dilate(claimed, _rect(3)))).astype(np.uint8)
        rot, inv = _rotate(src, angle)
        runs = cv2.morphologyEx(rot, cv2.MORPH_OPEN, np.ones((1, min_len), np.uint8))
        segs = _runs_to_segments(runs, rot, inv, angle, min_len, p)
        segments.extend(segs)
        if not diag:
            # gefundene Läufe als belegt markieren (zurückgedreht), damit die Diagonalen sie nicht doppeln
            back = runs.T if angle == 90 else runs
            claimed |= back
    covered = np.zeros_like(mask)
    for s in segments:
        cv2.fillConvexPoly(covered, _corners(s).astype(np.int32), 1)
    residual = _residual_segments(mask, covered, p)
    segments.extend(residual)
    return segments, {"t_max_px": round(t_max, 1), "residual": len(residual)}


def _seg_dist(s: Segment, o: Segment) -> float:
    """Kleinster Abstand zweier Mittellinien (0, wenn sie sich schneiden)."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    if ccw(s.a, o.a, o.b) != ccw(s.b, o.a, o.b) and ccw(s.a, s.b, o.a) != ccw(s.a, s.b, o.b):
        return 0.0

    def pt_seg(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
        return math.dist(p, (a[0] + t * dx, a[1] + t * dy))

    return min(pt_seg(s.a, o.a, o.b), pt_seg(s.b, o.a, o.b), pt_seg(o.a, s.a, s.b), pt_seg(o.b, s.a, s.b))


def _assess(segments: list[Segment], t_max: float, p: DetectParams) -> int:
    """Setzt die Sicherheit. Kurze Stücke ohne Berührung zu anderen Wänden (Schrift, Möbel,
    aber auch Pfeiler zwischen Fenstern) werden abgewertet, damit man sie im Editor prüft."""
    count = 0
    for i, s in enumerate(segments):
        touching = any(
            _seg_dist(s, o) <= (s.thickness_px + o.thickness_px) / 2 + p.touch_gap
            for j, o in enumerate(segments) if j != i
        )
        s.confidence = s.fill
        if not touching and s.length() < p.isolated_len_factor * t_max:
            s.confidence = round(s.fill * p.isolated_penalty, 2)
            count += 1
    return count


def _corners(s: Segment) -> np.ndarray:
    ax, ay = s.a
    bx, by = s.b
    L = s.length() or 1.0
    nx, ny = -(by - ay) / L * s.thickness_px / 2, (bx - ax) / L * s.thickness_px / 2
    return np.array([[ax + nx, ay + ny], [bx + nx, by + ny], [bx - nx, by - ny], [ax - nx, ay - ny]])


def detect(gray: np.ndarray, params: DetectParams | None = None) -> DetectResult:
    p = params or DetectParams()
    mask, direction = wall_mask(gray, p)
    segments, info = segments_from_mask(mask, p)
    info["raw_segments"] = len(segments)
    # Sicherheit vor der Nachbearbeitung bewerten: Schrott-Stücke sollen nicht durch
    # Anschließen an echte Wände „sicher“ wirken
    info["isolated"] = _assess(segments, info["t_max_px"], p)
    if p.clean:
        from .cleanup import (
            cleanup,  # hier importiert, weil cleanup die Segment-Klasse von hier nutzt
        )

        segments, cstats = cleanup(segments, info["t_max_px"])
        info.update(cstats.as_dict())
    stats = {"segments": len(segments), "mask_px": int(mask.sum()), **info}
    return DetectResult(segments, mask, direction, stats)


def render_debug(gray: np.ndarray, result: DetectResult) -> np.ndarray:
    """Bild mit Maske (rot) und erkannten Wänden (grün umrandet, Mittellinie blau) zur Kontrolle."""
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    sel = result.mask > 0
    vis[sel] = (0.6 * vis[sel] + 0.4 * np.array([0, 0, 255])).astype(np.uint8)
    for s in result.segments:
        poly = _corners(s).astype(np.int32)
        cv2.polylines(vis, [poly], True, (0, 150, 0) if s.confidence >= 0.75 else (0, 140, 255), 2)
        cv2.line(vis, (int(s.a[0]), int(s.a[1])), (int(s.b[0]), int(s.b[1])), (255, 0, 0), 1)
    return vis
