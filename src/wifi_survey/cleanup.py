"""Automatische Nachbearbeitung erkannter Wände (dieselben Schritte, die ein Anwender im
Editor von Hand machen würde, nur ohne Rückfrage und mit vorsichtigen Schwellen).

1. Stücke auf einer Linie verbinden: gleiche Richtung, kaum seitlicher Versatz, ähnliche
   Dicke und eine Lücke höchstens so groß wie eine Unterbrechung der Schraffur. Fenster und
   Türen (≥ 50 cm) bleiben offen, weil die Schwelle darunter liegt.
2. Ecken und Anschlüsse schließen: Endet eine Wand kurz vor einer anderen (nicht parallelen)
   Wand, wird sie bis zu deren Außenkante verlängert bzw. darauf gekürzt.
3. Verwerfen: Stücke, die kürzer als ihre halbe Dicke sind, und Stücke, die fast ganz in
   einer anderen Wand liegen (doppelt erkannt).

Alle Längen sind Pixel des Stockwerkbilds; Schwellen sind relativ zur größten Wanddicke.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .walls import Segment


@dataclass
class CleanupParams:
    gap_factor: float = 0.8        # größte überbrückte Lücke = gap_factor × größte Wanddicke
    offset_factor: float = 0.5     # erlaubter seitlicher Versatz = offset_factor × größere Dicke
    thick_tolerance: float = 0.25  # Dicken dürfen sich um so viel (relativ) unterscheiden
    angle_tol_deg: float = 3.0
    reach_factor: float = 1.0      # Ecken schließen bis zu reach_factor × größte Wanddicke Abstand
    min_corner_angle_deg: float = 30.0
    credible: float = 0.75         # nur Wände mit mindestens dieser Sicherheit werden angeschlossen
    tiny_factor: float = 0.5       # kürzer als tiny_factor × Dicke = verwerfen
    contained_share: float = 0.9   # Anteil der Fläche, ab dem ein Stück als doppelt gilt


@dataclass
class CleanupStats:
    merged: int = 0
    joined: int = 0
    dropped: int = 0

    def as_dict(self) -> dict:
        return {"merged": self.merged, "joined": self.joined, "dropped": self.dropped}


def _dir(s: Segment) -> tuple[float, float]:
    L = s.length() or 1.0
    return (s.b[0] - s.a[0]) / L, (s.b[1] - s.a[1]) / L


def _parallel(s: Segment, o: Segment, tol_deg: float) -> bool:
    u, v = _dir(s), _dir(o)
    return abs(u[0] * v[1] - u[1] * v[0]) <= math.sin(math.radians(tol_deg))


def merge_collinear(segs: list[Segment], t_max: float, p: CleanupParams) -> tuple[list[Segment], int]:
    n = len(segs)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    gap_max = p.gap_factor * t_max
    for i in range(n):
        s = segs[i]
        u = _dir(s)
        for j in range(i + 1, n):
            o = segs[j]
            if not _parallel(s, o, p.angle_tol_deg):
                continue
            tmax = max(s.thickness_px, o.thickness_px)
            if abs(s.thickness_px - o.thickness_px) > max(3.0, p.thick_tolerance * tmax):
                continue
            mx, my = (o.a[0] + o.b[0]) / 2, (o.a[1] + o.b[1]) / 2
            off = abs(-u[1] * (mx - s.a[0]) + u[0] * (my - s.a[1]))
            if off > p.offset_factor * tmax:
                continue
            t0, t1 = sorted([0.0, s.length()])
            q = sorted([(o.a[0] - s.a[0]) * u[0] + (o.a[1] - s.a[1]) * u[1],
                        (o.b[0] - s.a[0]) * u[0] + (o.b[1] - s.a[1]) * u[1]])
            gap = max(q[0] - t1, t0 - q[1])
            if gap <= gap_max:
                parent[find(j)] = find(i)

    groups: dict[int, list[Segment]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(segs[i])
    out, merged = [], 0
    for members in groups.values():
        if len(members) == 1:
            out.append(members[0])
            continue
        merged += len(members) - 1
        ref = max(members, key=lambda s: s.length())
        u = _dir(ref)
        nrm = (-u[1], u[0])
        lengths = [max(m.length(), 1e-6) for m in members]
        total = sum(lengths)
        offs = [((m.a[0] + m.b[0]) / 2 - ref.a[0]) * nrm[0] + ((m.a[1] + m.b[1]) / 2 - ref.a[1]) * nrm[1] for m in members]
        off = sum(o * w for o, w in zip(offs, lengths)) / total
        along = [((pt[0] - ref.a[0]) * u[0] + (pt[1] - ref.a[1]) * u[1]) for m in members for pt in (m.a, m.b)]
        lo, hi = min(along), max(along)
        base = (ref.a[0] + nrm[0] * off, ref.a[1] + nrm[1] * off)
        thick = sum(m.thickness_px * w for m, w in zip(members, lengths)) / total
        fill = sum(m.fill * w for m, w in zip(members, lengths)) / total
        conf = sum(m.confidence * w for m, w in zip(members, lengths)) / total
        out.append(Segment((round(base[0] + u[0] * lo, 1), round(base[1] + u[1] * lo, 1)),
                           (round(base[0] + u[0] * hi, 1), round(base[1] + u[1] * hi, 1)),
                           round(thick, 1), ref.angle, round(fill, 2), round(conf, 2)))
    return out, merged


def _intersection(s: Segment, o: Segment):
    r = (s.b[0] - s.a[0], s.b[1] - s.a[1])
    q = (o.b[0] - o.a[0], o.b[1] - o.a[1])
    den = r[0] * q[1] - r[1] * q[0]
    if abs(den) < 1e-9:
        return None
    t = ((o.a[0] - s.a[0]) * q[1] - (o.a[1] - s.a[1]) * q[0]) / den
    return (s.a[0] + t * r[0], s.a[1] + t * r[1])


def join_corners(segs: list[Segment], t_max: float, p: CleanupParams) -> int:
    """Verlängert/kürzt Wandenden bis zur Außenkante einer nahen, nicht parallelen Wand."""
    reach = p.reach_factor * t_max
    joined = 0
    for s in segs:
        L = s.length()
        if L < 1 or s.confidence < p.credible:
            continue
        for end in ("a", "b"):
            e = getattr(s, end)
            far = s.b if end == "a" else s.a
            best = None
            for o in segs:
                if o is s or o.confidence < p.credible or _parallel(s, o, p.min_corner_angle_deg):
                    continue
                P = _intersection(s, o)
                if P is None:
                    continue
                # Schnittpunkt muss auf (oder knapp neben) der anderen Wand liegen
                Lo = o.length() or 1.0
                to = ((P[0] - o.a[0]) * (o.b[0] - o.a[0]) + (P[1] - o.a[1]) * (o.b[1] - o.a[1])) / (Lo * Lo)
                if to < -reach / Lo or to > 1 + reach / Lo:
                    continue
                # ... und auf der Seite dieses Endes liegen (nie das andere Ende verschieben)
                ts = ((P[0] - s.a[0]) * (s.b[0] - s.a[0]) + (P[1] - s.a[1]) * (s.b[1] - s.a[1])) / (L * L)
                if (end == "a" and ts > 0.15) or (end == "b" and ts < 0.85):
                    continue
                dx, dy = P[0] - far[0], P[1] - far[1]
                dl = math.hypot(dx, dy) or 1.0
                target = (P[0] + dx / dl * o.thickness_px / 2, P[1] + dy / dl * o.thickness_px / 2)
                # Lücke bis zur nahen Kante der anderen Wand (negativ: Ende ragt schon hinein)
                gap = math.dist(e, P) - o.thickness_px / 2
                moved = math.dist(e, target)  # begrenzt auch das Kürzen überstehender Enden
                if gap <= reach and moved <= reach + o.thickness_px and (best is None or gap < best[0]):
                    best = (gap, target)
            if best and math.dist(e, best[1]) > 0.5:
                setattr(s, end, (round(best[1][0], 1), round(best[1][1], 1)))
                joined += 1
    return joined


def _poly(s: Segment) -> np.ndarray:
    L = s.length() or 1.0
    nx, ny = -(s.b[1] - s.a[1]) / L * s.thickness_px / 2, (s.b[0] - s.a[0]) / L * s.thickness_px / 2
    return np.array([[s.a[0] + nx, s.a[1] + ny], [s.b[0] + nx, s.b[1] + ny],
                     [s.b[0] - nx, s.b[1] - ny], [s.a[0] - nx, s.a[1] - ny]], np.float32)


def drop_tiny_and_contained(segs: list[Segment], p: CleanupParams) -> tuple[list[Segment], int]:
    keep = [s for s in segs if s.length() >= p.tiny_factor * s.thickness_px]
    dropped = len(segs) - len(keep)
    # doppelt erkannte Stücke: Fläche liegt fast ganz in einer größeren Wand
    keep.sort(key=lambda s: s.length() * s.thickness_px, reverse=True)
    polys = [_poly(s) for s in keep]
    out: list[Segment] = []
    out_polys: list[np.ndarray] = []
    for s, poly in zip(keep, polys):
        area = s.length() * s.thickness_px
        contained = False
        for q in out_polys:
            inter, _ = cv2.intersectConvexConvex(poly, q)
            if area > 0 and inter / area >= p.contained_share:
                contained = True
                break
        if contained:
            dropped += 1
        else:
            out.append(s)
            out_polys.append(poly)
    return out, dropped


def cleanup(segs: list[Segment], t_max: float, params: CleanupParams | None = None) -> tuple[list[Segment], CleanupStats]:
    p = params or CleanupParams()
    stats = CleanupStats()
    segs, stats.merged = merge_collinear(list(segs), t_max, p)
    stats.joined = join_corners(segs, t_max, p)
    segs, stats.dropped = drop_tiny_and_contained(segs, p)
    # nach dem Verlängern können wieder Stücke aneinanderstoßen
    segs, more = merge_collinear(segs, t_max, p)
    stats.merged += more
    return segs, stats
