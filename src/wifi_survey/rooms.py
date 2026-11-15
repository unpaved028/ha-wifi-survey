"""Räume eines Stockwerks (Entscheidung 0014): Die Suche nennt die wahrscheinlichsten Räume statt einer Stelle.

Ein Raum ist eine zusammenhängende Fläche im Haus, die Wände begrenzen. Lücken zwischen Wänden bis DOOR_M
gelten als Tür und trennen Räume; breitere Öffnungen (offene Küche, Durchgang) verbinden die Flächen zu einem Raum.

Namen, in dieser Reihenfolge:
1. vom Anwender: ein Namensschild (models.RoomLabel) im Raum,
2. aus Home Assistant: die Bereiche der Geräte im Raum, häufigste zuerst,
3. „Raum N“.

Gerechnet wird auf einem feinen Raster (RES_M), das Ergebnis liegt auf dem Raster der Auswertung
(evaluate.floor_grid), damit die Suche ihre Wahrscheinlichkeit je Raum aufsummieren kann.
"""

from __future__ import annotations

from collections import Counter

import cv2
import numpy as np

from . import evaluate as ev
from .models import Floor

# Lücken bis zu dieser Breite (Türen) trennen Räume. Türöffnungen in Plänen und erkannten Wänden sind oft breiter als
# die Tür (Rohbaumaß, Lücken der Erkennung). Die vier Stockwerke des Testhauses (13.11.2026): Mit 1,0–1,2 m entstehen Räume, die
# zu den Bereichen in HA passen (KG 5, EG 6, OG 6, DG 5); ab 1,3 m verschwinden schmale Gänge, und Räume wachsen
# zusammen (EG: Küche und Gang 81 m²).
DOOR_M = 1.2
MIN_ROOM_M2 = 1.0       # kleinere Flächen (Nischen, Schächte) gehören zum Nachbarraum
RES_M = 0.05            # feines Raster für Wände und Türen
MAX_NAMES = 3           # höchstens so viele Bereiche aus HA im Namen
SIMPLIFY_M = 0.1        # Umrisse bis auf diese Abweichung vereinfachen

_cache: dict[tuple, dict] = {}


def compute(floor: Floor, areas: dict[str, str] | None = None) -> dict:
    """Räume des Stockwerks. areas: Gerätschlüssel → Bereich in Home Assistant (für Namen).

    Liefert {"rooms": [...], "labels": Raster der Auswertung mit Raumnummer je Zelle (0 = außerhalb),
    "grid": wie evaluate.floor_grid}. Je Raum: id (1 …), name, source („user“, „ha“, „auto“), area_m2,
    anchor (Bildpixel, gut innerhalb), contours (Bildpixel), labels (Indizes der Namensschilder darin)."""
    if not floor.scale:
        raise ValueError("Für Räume braucht das Stockwerk einen Maßstab.")
    areas = areas or {}
    key = (floor.id, floor.model_dump_json(include={"walls", "outline", "scale", "devices", "room_labels",
                                                    "survey", "found"}),
           tuple(sorted((k, v) for k, v in areas.items() if any(d.key == k for d in floor.devices))))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    ppm = floor.scale.px_per_m
    x0, y0, cell, gx, gy = ev.floor_grid(floor)
    inside_grid, _ = ev.interior_mask(floor, ppm, gx, gy)
    rows, cols = gx.shape
    fpx = RES_M * ppm                                   # Bildpixel je feinem Pixel
    W, H = int(np.ceil(cols * cell / fpx)), int(np.ceil(rows * cell / fpx))
    fx, fy = np.meshgrid(x0 + (np.arange(W) + 0.5) * fpx, y0 + (np.arange(H) + 0.5) * fpx)
    inside, _ = ev.interior_mask(floor, ppm, fx, fy)

    def to_f(p):
        return round((p[0] - x0) / fpx - 0.5), round((p[1] - y0) / fpx - 0.5)

    walls = np.zeros((H, W), np.uint8)
    for w in floor.walls:
        cv2.line(walls, to_f(w.a), to_f(w.b), 1, max(1, round(w.thickness_px / fpx)))
    # Türen schließen: Wände um DOOR_M/2 verbreitern, dann wachsen Lücken bis DOOR_M zu (Schließen mit Dilatation und
    # Erosion reicht nicht: Es lässt Lücken in dünnen, geraden Wänden offen). Gänge, die schmaler als DOOR_M sind,
    # verschwinden dabei; ihre Fläche fällt unten dem Nachbarraum zu, wie die Wandflächen selbst.
    r = max(1, round(DOOR_M / 2 / RES_M))
    grown = cv2.dilate(walls, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    free = (inside & (grown == 0)).astype(np.uint8)
    n, lab = cv2.connectedComponents(free, connectivity=4)
    sizes = np.bincount(lab.ravel(), minlength=n) * RES_M * RES_M
    small = np.nonzero(sizes < MIN_ROOM_M2)[0]
    lab[np.isin(lab, small)] = 0
    # Wände, Türlinien und kleine Reste dem nächsten Raum zuordnen
    if (lab > 0).any():
        _, near = cv2.distanceTransformWithLabels((lab == 0).astype(np.uint8), cv2.DIST_L2, 5,
                                                  labelType=cv2.DIST_LABEL_PIXEL)
        ys, xs = np.nonzero(lab > 0)
        of = np.zeros(int(near.max()) + 1, np.int32)
        of[near[ys, xs]] = lab[ys, xs]
        lab = np.where(inside, of[near], 0)
    ids = [int(k) for k in np.unique(lab) if k > 0]
    order = sorted(ids, key=lambda k: -int((lab == k).sum()))
    renum = np.zeros(int(lab.max()) + 1, np.int32)
    for i, k in enumerate(order, 1):
        renum[k] = i
    lab = renum[lab]

    def room_at(p) -> int:
        c, r = to_f(p)
        return int(lab[r, c]) if 0 <= r < H and 0 <= c < W else 0

    rooms = []
    for k in range(1, len(order) + 1):
        mask = (lab == k).astype(np.uint8)
        dist = cv2.distanceTransform(np.pad(mask, 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
        r, c = np.unravel_index(int(np.argmax(dist)), dist.shape)
        cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = []
        for ct in cs:
            ct = cv2.approxPolyDP(ct, SIMPLIFY_M / RES_M, True)
            if len(ct) >= 3:
                contours.append([[round(x0 + (float(pt[0][0]) + 0.5) * fpx, 1), round(y0 + (float(pt[0][1]) + 0.5) * fpx, 1)]
                                 for pt in ct])
        rooms.append({"id": k, "area_m2": round(float(mask.sum()) * RES_M * RES_M, 1),
                      "anchor": [round(float(x0 + (c + 0.5) * fpx), 1), round(float(y0 + (r + 0.5) * fpx), 1)],
                      "contours": contours, "labels": [], "devices": []})
    for i, rl in enumerate(floor.room_labels):
        k = room_at(rl.pos)
        if k:
            rooms[k - 1]["labels"].append(i)
    for d in floor.devices:
        k = room_at(d.pos)
        if k:
            rooms[k - 1]["devices"].append(d.key)
    for i, rm in enumerate(rooms, 1):
        found = Counter(areas[key] for key in rm["devices"] if areas.get(key))
        if rm["labels"]:
            rm["name"], rm["source"] = floor.room_labels[rm["labels"][0]].name, "user"
        elif found:
            top = sorted(found.items(), key=lambda t: (-t[1], t[0].lower()))[:MAX_NAMES]
            rm["name"], rm["source"] = " / ".join(a for a, _ in top), "ha"
        else:
            rm["name"], rm["source"] = f"Raum {i}", "auto"
        rm["ha_areas"] = [a for a, _ in sorted(found.items(), key=lambda t: (-t[1], t[0].lower()))]
    # gleiche Namen aus HA (Geräte eines Bereichs in zwei Räumen) durchzählen, damit die Liste der Suche eindeutig bleibt
    seen: Counter[str] = Counter()
    for rm in rooms:
        if rm["source"] == "ha":
            seen[rm["name"]] += 1
            if seen[rm["name"]] > 1:
                rm["name"] = f"{rm['name']} {seen[rm['name']]}"

    # Raster der Auswertung: Raumnummer an der Zellmitte; Zellen im Haus ohne Raum zum nächsten
    ci = np.clip(((gx - x0) / fpx).astype(int), 0, W - 1)
    ri = np.clip(((gy - y0) / fpx).astype(int), 0, H - 1)
    grid_lab = np.where(inside_grid, lab[ri, ci], 0).astype(np.int32)
    gap = inside_grid & (grid_lab == 0)
    if gap.any() and (grid_lab > 0).any():
        _, near = cv2.distanceTransformWithLabels((grid_lab == 0).astype(np.uint8), cv2.DIST_L2, 3,
                                                  labelType=cv2.DIST_LABEL_PIXEL)
        ys, xs = np.nonzero(grid_lab > 0)
        of = np.zeros(int(near.max()) + 1, np.int32)
        of[near[ys, xs]] = grid_lab[ys, xs]
        grid_lab = np.where(gap, of[near], grid_lab)
    out = {"rooms": rooms, "labels": grid_lab,
           "grid": {"x": float(x0), "y": float(y0), "cell_px": float(cell), "cols": int(cols), "rows": int(rows)}}
    if len(_cache) > 32:
        _cache.clear()
    _cache[key] = out
    return out


def public(res: dict) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "devices"} for r in res["rooms"]]


def ranking(dens: dict[str, np.ndarray], rooms_by_floor: dict[str, dict], floor_names: dict[str, str]) -> list[dict]:
    """Wahrscheinlichkeit je Raum (Summe über seine Zellen), über alle Stockwerke, die wahrscheinlichsten zuerst.
    dens: normierte Dichte je Stockwerk auf dem Raster der Auswertung (locate._summarize, „_dens“)."""
    out = []
    for fid, d in dens.items():
        rb = rooms_by_floor.get(fid)
        if rb is None or rb["labels"].shape != d.shape:
            continue
        sums = np.bincount(rb["labels"].ravel(), weights=d.ravel(), minlength=len(rb["rooms"]) + 1)
        for rm in rb["rooms"]:
            out.append({"key": f"{fid}:{rm['id']}", "floor_id": fid, "floor": floor_names.get(fid, ""), "room": rm["id"],
                        "name": rm["name"], "area_m2": rm["area_m2"], "p": float(sums[rm["id"]])})
    out.sort(key=lambda r: -r["p"])
    for i, r in enumerate(out, 1):
        r["rank"] = i
        r["share"] = round(r.pop("p") * 100)
    return out


def room_key_at(rooms_by_floor: dict[str, dict], floor: Floor, pos) -> str | None:
    """Raum (Schlüssel wie in ranking) an einer Stelle des Stockwerks, None außerhalb."""
    rb = rooms_by_floor.get(floor.id)
    if rb is None:
        return None
    g = rb["grid"]
    c, r = int((pos[0] - g["x"]) // g["cell_px"]), int((pos[1] - g["y"]) // g["cell_px"])
    if not (0 <= r < g["rows"] and 0 <= c < g["cols"]):
        return None
    k = int(rb["labels"][r, c])
    return f"{floor.id}:{k}" if k else None
