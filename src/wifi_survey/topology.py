"""Auswertungen auf der Wandliste eines Stockwerks (ohne Bildverarbeitung des Scans)."""

from __future__ import annotations

import math
from collections.abc import Iterable

import cv2
import numpy as np

from .models import Wall

RAY_ANGLES_DEG = (-45.0, -20.0, 0.0, 20.0, 45.0)  # Strahlenfächer um die Wandnormale
RAY_STEP_PX = 2.0
ESCAPE_SHARE = 0.5  # so viele Strahlen einer Seite müssen ins Freie gelangen


def _corners(w: Wall) -> np.ndarray:
    (ax, ay), (bx, by) = w.a, w.b
    length = math.dist(w.a, w.b) or 1.0
    nx, ny = -(by - ay) / length * w.thickness_px / 2, (bx - ax) / length * w.thickness_px / 2
    return np.array([[ax + nx, ay + ny], [bx + nx, by + ny], [bx - nx, by - ny], [ax - nx, ay - ny]])


def _escaped(mask: np.ndarray, starts: np.ndarray, dirs: np.ndarray, chunk: int = 1500) -> np.ndarray:
    """Für jeden Strahl: erreicht er den Bildrand, ohne eine Wand zu treffen?"""
    h, w = mask.shape
    steps = np.arange(0.0, math.hypot(w, h) + RAY_STEP_PX, RAY_STEP_PX)
    out = np.zeros(len(starts), bool)
    for i in range(0, len(starts), chunk):
        p = starts[i:i + chunk, None, :] + dirs[i:i + chunk, None, :] * steps[None, :, None]
        xs = np.rint(p[..., 0]).astype(np.int32)
        ys = np.rint(p[..., 1]).astype(np.int32)
        inside = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        hit = np.zeros(inside.shape, bool)
        hit[inside] = mask[ys[inside], xs[inside]] > 0
        # erster Austritt aus dem Bild bzw. erster Treffer
        exit_idx = np.where(inside.all(axis=1), steps.size, np.argmin(inside, axis=1))
        hit_idx = np.where(hit.any(axis=1), np.argmax(hit, axis=1), steps.size)
        out[i:i + chunk] = hit_idx >= exit_idx
    return out


def exterior_walls(walls: Iterable[Wall], width: int, height: int) -> list[str]:
    """IDs der Wände, die an den Außenraum grenzen.

    Von beiden Längsseiten jeder Wand gehen Strahlenfächer nach außen. Eine Seite gilt als
    Außenseite, wenn mindestens die Hälfte der Strahlen den Bildrand erreicht, ohne eine
    andere Wand zu treffen. Nischen zwischen Lichtschächten oder Erkern stören so nicht,
    und ein einzelnes Fenster gegenüber macht eine Innenwand nicht zur Außenwand.
    """
    walls = [w for w in walls if math.dist(w.a, w.b) >= 1]
    if not walls:
        return []
    mask = np.zeros((height, width), np.uint8)
    for w in walls:
        cv2.fillConvexPoly(mask, np.rint(_corners(w)).astype(np.int32), 1)

    starts, dirs, owner = [], [], []
    angles = np.radians(RAY_ANGLES_DEG)
    for wi, w in enumerate(walls):
        length = math.dist(w.a, w.b)
        ux, uy = (w.b[0] - w.a[0]) / length, (w.b[1] - w.a[1]) / length
        k = int(min(25, max(3, length // 10)))
        for side in (-1, 1):
            nx, ny = -uy * side, ux * side
            off = w.thickness_px / 2 + 3
            for t in np.linspace(0.1, 0.9, k):
                sx = w.a[0] + ux * t * length + nx * off
                sy = w.a[1] + uy * t * length + ny * off
                for ang in angles:
                    c, s = math.cos(ang), math.sin(ang)
                    starts.append((sx, sy))
                    dirs.append((nx * c - ny * s, nx * s + ny * c))
                    owner.append(wi * 2 + (0 if side < 0 else 1))
    esc = _escaped(mask, np.array(starts), np.array(dirs))
    owner = np.array(owner)
    share = np.bincount(owner, weights=esc, minlength=2 * len(walls)) / np.maximum(
        np.bincount(owner, minlength=2 * len(walls)), 1)
    return [w.id for wi, w in enumerate(walls) if max(share[2 * wi], share[2 * wi + 1]) >= ESCAPE_SHARE]


def covered_share(w: Wall, others: Iterable[Wall]) -> float:
    """Größter Anteil der Fläche von w, der in einer der anderen Wände liegt (0..1)."""
    area = math.dist(w.a, w.b) * w.thickness_px
    if area <= 0:
        return 1.0
    poly = _corners(w).astype(np.float32)
    best = 0.0
    for o in others:
        inter, _ = cv2.intersectConvexConvex(poly, _corners(o).astype(np.float32))
        best = max(best, inter / area)
    return min(best, 1.0)
