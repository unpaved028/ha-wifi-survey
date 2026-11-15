"""Auswertung: Messwerte je Gerät, Ausbreitungsmodell über alle Stockwerke, Karten, Hinweise.

1. Messwerte je platziertem Gerät: verbundener Zugangspunkt mit Signal, bester erreichbarer
   Zugangspunkt laut WLAN-Scan (nur Shellys), Bewertung und „klebt“-Hinweis.
2. Ausbreitungsmodell für alle Zugangspunkte im Haus (Mehrwandmodell, angelehnt an COST 231):
       RSSI = P0 − 20·log10(d) − k · Σ Wandverlust − C · F(n)
   - d: Abstand im Raum in Metern (mindestens 0,5 m). Ausgerichtete Stockwerke liegen in einem
     gemeinsamen Gebäudesystem, übereinander im Abstand der Geschosshöhe.
   - Wandverlust: Startwert je Material (dB/cm) × Dicke, bei schrägem Durchgang länger. Auf jedem
     Stockwerk zählen die Wände des Abschnitts, den die Strecke auf dessen Höhe zurücklegt.
   - F(n) = n^((n+2)/(n+1) − 0,46) für n durchquerte Decken: 1 → 1, 2 → 1,83, 3 → 2,38.
   P0 je Zugangspunkt, Wandfaktor k und Deckendämpfung C werden gemeinsam an allen Messpunkten
   geschätzt: gewichtete kleinste Quadrate mit schwachen Vorgaben, Ausreißer gedämpft (Huber).
   Mit wenigen Messpunkten bleiben die Werte nahe an den Vorgaben.
3. Karten je Stockwerk (Raster 0,2 m): je Zugangspunkt und „beste Versorgung“; Abdeckung im Haus
   und Anteil der Fläche, auf der ein Zugangspunkt am stärksten ankommt.
4. Hinweise in Klartext.

Stockwerke ohne Ausrichtung rechnen nur mit ihren eigenen Zugangspunkten.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .catalog import norm_mac
from .models import Floor, Project
from .survey import valid_rssi

# Startwerte der Wanddämpfung bei 2,4 GHz in dB je cm Dicke (übliche Größenordnungen, keine
# Messwerte). Das Modell skaliert sie gemeinsam mit dem Faktor k auf die Messungen.
LOSS_DB_PER_CM = {
    "hochlochziegel": 0.30,
    "beton": 0.45,
    "stahlbeton": 0.60,
    "trockenbau": 0.20,
    "glas": 0.40,
    "holz": 0.15,
    "metall": 2.00,
    "kunststoff": 0.05,
    "sonstiges": 0.30,
}
DEFAULT_P0 = -40.0      # dBm in 1 m Abstand, falls nicht kalibrierbar
GRID_M = 0.2
MIN_D_M = 0.5
FIT_MIN_D_M = 1.0   # näher am Zugangspunkt stimmt kein Ausbreitungsmodell: nicht zum Eichen
K_RANGE = (0.2, 3.0)
C_RANGE = (0.0, 40.0)
FLOOR_HEIGHT_M = 2.8    # Geschosshöhe (Annahme), geht nur in den Abstand ein
DEVICE_HEIGHT_M = 1.0   # Geräte und Zugangspunkte etwa auf Tischhöhe
# Vorgaben für die Schätzung (Mittelwert, Streuung); die Decke: 20 cm Stahlbeton × 0,6 dB/cm
PRIOR_P0 = (DEFAULT_P0, 10.0)
PRIOR_K = (1.0, 0.7)
PRIOR_C = (12.0, 8.0)
# Signal, mit dem der Zugangspunkt ein Gerät empfängt (FRITZ!Box-Sicht), gegenüber dem, was Geräte vom
# Zugangspunkt empfangen (Shelly-Scan, Handy): Sendeleistung und Antennen unterscheiden sich
PRIOR_UP = (0.0, 6.0)
# 5 GHz gegenüber 2,4 GHz: Freiraum in 1 m etwa 7 dB weniger (20·log10(5,5/2,44)); Wände dämpfen stärker,
# das bildet der Abschlag nur im Mittel ab. Geschätzt aus 5-GHz-Messwerten, gestützt auf N0_5 Werte Vorgabe
PRIOR_5 = -7.0
N0_5 = 3.0
# Eigenes Modell für 5 GHz (P0 je Zugangspunkt, Wandfaktor, Decke, Abgleich der FRITZ!Box-Sicht), Vorgaben aus dem
# 2,4-GHz-Modell plus Abschlag mit diesen Streuungen. Kreuzprobe im Testhaus (03.11.2026, 164 Werte): 7,3 statt
# 7,7 dB mit dem Abschlag allein; eine Decke dämpft dort 14 statt 10 dB.
PRIOR5_SD = {"p0_sd": 5.0, "k_sd": 0.5, "c_sd": 6.0, "up_sd": 3.0}
NOISE_DB = 6.0          # übliche Streuung einzelner Messwerte (Gerät, Einbauort, Zeitpunkt)
HUBER = 1.5             # Messwerte, die mehr als 1,5 × Streuung abweichen, zählen weniger
STICKY_DB = 6
RATINGS = ((-60, "gut"), (-70, "ausreichend"), (-80, "schwach"), (-999, "kritisch"))

# Farbskala dBm -> RGB (grün = stark, rot = schwach)
_STOPS = [(-40, (0, 104, 55)), (-55, (26, 152, 80)), (-65, (145, 207, 96)), (-70, (254, 224, 139)),
          (-75, (253, 174, 97)), (-80, (244, 109, 67)), (-90, (165, 0, 38))]


def rating(rssi: float | None) -> str | None:
    if rssi is None:
        return None
    return next(label for limit, label in RATINGS if rssi >= limit)


def colorize(values: np.ndarray, alpha: int = 170) -> np.ndarray:
    """dBm-Raster -> RGBA (NaN = durchsichtig)."""
    xs = np.array([s[0] for s in _STOPS], float)[::-1]
    cols = np.array([s[1] for s in _STOPS], float)[::-1]
    v = np.clip(values, xs[0], xs[-1])
    rgb = np.stack([np.interp(v, xs, cols[:, c]) for c in range(3)], axis=-1)
    a = np.where(np.isnan(values), 0, alpha)
    return np.dstack([np.nan_to_num(rgb), a]).astype(np.uint8)


def legend() -> list[dict]:
    return [{"dbm": d, "rgb": list(c)} for d, c in _STOPS]


def path_loss(src: np.ndarray, pts: np.ndarray, w1: np.ndarray, w2: np.ndarray, loss: np.ndarray,
              t0: float = 0.0, t1: float = 1.0) -> np.ndarray:
    """Summe der Wandverluste (dB, Startwerte) auf den Strecken src -> pts (N Punkte).

    Es zählen nur Wände im Abschnitt t0..t1 der Strecke (0 = src, 1 = Punkt)."""
    if len(loss) == 0:
        return np.zeros(len(pts))
    r = pts - src                       # N×2
    s = w2 - w1                         # M×2
    q = w1 - src                        # M×2
    den = r[:, None, 0] * s[None, :, 1] - r[:, None, 1] * s[None, :, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (q[:, 0] * s[:, 1] - q[:, 1] * s[:, 0])[None, :] / den
        u = (q[None, :, 0] * r[:, None, 1] - q[None, :, 1] * r[:, None, 0]) / den
        hit = (np.abs(den) > 1e-9) & (t > t0) & (t < t1) & (u >= 0) & (u <= 1)
        sin = np.abs(den) / (np.linalg.norm(r, axis=1)[:, None] * np.linalg.norm(s, axis=1)[None, :])
        factor = 1.0 / np.maximum(np.nan_to_num(sin), 0.3)   # schräger Durchgang = längerer Weg
    return (hit * factor * loss[None, :]).sum(axis=1)


def path_loss_many(srcs: np.ndarray, pts: np.ndarray, w1: np.ndarray, w2: np.ndarray, loss: np.ndarray,
                   t0: float = 0.0, t1: float = 1.0) -> np.ndarray:
    """Wie path_loss, für K Quellen auf einmal (K×N). Für viele Quellen und wenige Punkte."""
    if len(loss) == 0:
        return np.zeros((len(srcs), len(pts)))
    r = pts[None, :, :] - srcs[:, None, :]              # K×N×2
    s = w2 - w1                                          # M×2
    q = w1[None, :, :] - srcs[:, None, :]                # K×M×2
    den = r[..., 0, None] * s[:, 1] - r[..., 1, None] * s[:, 0]          # K×N×M
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (q[..., 0] * s[:, 1] - q[..., 1] * s[:, 0])[:, None, :] / den
        u = (q[:, None, :, 0] * r[..., 1, None] - q[:, None, :, 1] * r[..., 0, None]) / den
        hit = (np.abs(den) > 1e-9) & (t > t0) & (t < t1) & (u >= 0) & (u <= 1)
        sin = np.abs(den) / (np.linalg.norm(r, axis=-1)[..., None] * np.linalg.norm(s, axis=1))
        factor = 1.0 / np.maximum(np.nan_to_num(sin), 0.3)
    return (hit * factor * loss).sum(axis=-1)


def ceiling_factor(n: int) -> float:
    """Wirkung von n Decken (COST 231): jede weitere Decke dämpft etwas weniger als die erste."""
    return 0.0 if n <= 0 else n ** ((n + 2) / (n + 1) - 0.46)


def _groups(floors: list[Floor]) -> dict[str, str]:
    """Stockwerk-ID -> Gruppe: über die Ausrichtung verbundene Stockwerke teilen ein Gebäudesystem."""
    parent = {f.id: f.id for f in floors}

    def root(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    for f in floors:
        if f.reference_floor in parent:
            parent[root(f.id)] = root(f.reference_floor)
    return {f.id: root(f.id) for f in floors}


class Building:
    """Stockwerke mit Maßstab in Metern; ausgerichtete Stockwerke in einem gemeinsamen System."""

    def __init__(self, project: Project):
        self.floors = [f for f in project.floors if f.scale]
        self.group = _groups(self.floors)
        parts: dict[tuple[str, int], list] = {}
        for f in self.floors:
            if not f.walls:
                continue
            a = self.to_m(f, [w.a for w in f.walls])
            b = self.to_m(f, [w.b for w in f.walls])
            loss = np.array([LOSS_DB_PER_CM.get(w.material, 0.3) * w.thickness_px / f.scale.px_per_m * 100
                             for w in f.walls])
            parts.setdefault((self.group[f.id], f.level), []).append((a, b, loss))
        self._walls = {k: tuple(np.concatenate(x) for x in zip(*v)) for k, v in parts.items()}

    @staticmethod
    def to_m(floor: Floor, pts) -> np.ndarray:
        """Bildpixel des Stockwerks -> Gebäude (Meter)."""
        p = np.asarray(pts, float).reshape(-1, 2) / floor.scale.px_per_m
        t = floor.transform
        c, s = math.cos(math.radians(t.rot_deg)), math.sin(math.radians(t.rot_deg))
        return np.stack([p[:, 0] * c - p[:, 1] * s + t.dx_m, p[:, 0] * s + p[:, 1] * c + t.dy_m], axis=1)

    @staticmethod
    def to_px(floor: Floor, pts_m) -> np.ndarray:
        """Gebäude (Meter) -> Bildpixel des Stockwerks."""
        t = floor.transform
        q = np.asarray(pts_m, float).reshape(-1, 2) - [t.dx_m, t.dy_m]
        c, s = math.cos(math.radians(t.rot_deg)), math.sin(math.radians(t.rot_deg))
        return np.stack([q[:, 0] * c + q[:, 1] * s, -q[:, 0] * s + q[:, 1] * c], axis=1) * floor.scale.px_per_m

    def linked(self, fa: Floor, fb: Floor) -> bool:
        return fa.id == fb.id or (fa.id in self.group and self.group[fa.id] == self.group.get(fb.id))

    def aligned(self, floor: Floor) -> bool:
        g = self.group.get(floor.id)
        return sum(1 for v in self.group.values() if v == g) > 1

    def walls_at(self, group: str, level: int):
        empty = np.zeros((0, 2))
        return self._walls.get((group, level), (empty, empty, np.zeros(0)))

    def link(self, fa: Floor, pa: np.ndarray, fb: Floor, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
        """Abstand im Raum, Wandverlust (Startwerte) und Zahl der Decken von pa (auf fa) zu den
        Punkten pts (auf fb), alles in Gebäudemetern."""
        g = self.group[fa.id]
        la, lb = fa.level, fb.level
        d3 = np.sqrt(((pts - pa) ** 2).sum(axis=1) + ((lb - la) * FLOOR_HEIGHT_M) ** 2)
        if la == lb:
            return d3, path_loss(pa, pts, *self.walls_at(g, la)), 0
        wall = np.zeros(len(pts))
        for lvl, t0, t1 in _link_parts(la, lb):   # Abschnitt der Strecke auf Höhe dieses Stockwerks
            wall += path_loss(pa, pts, *self.walls_at(g, lvl), t0, t1)
        return d3, wall, abs(lb - la)

    def link_many(self, fa: Floor, srcs: np.ndarray, fb: Floor, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
        """Wie link, für K Quellpunkte auf fa: Abstand und Wandverlust als K×N."""
        g = self.group[fa.id]
        la, lb = fa.level, fb.level
        d3 = np.sqrt(((pts[None, :, :] - srcs[:, None, :]) ** 2).sum(axis=-1) + ((lb - la) * FLOOR_HEIGHT_M) ** 2)
        if la == lb:
            return d3, path_loss_many(srcs, pts, *self.walls_at(g, la)), 0
        wall = np.zeros(d3.shape)
        for lvl, t0, t1 in _link_parts(la, lb):
            wall += path_loss_many(srcs, pts, *self.walls_at(g, lvl), t0, t1)
        return d3, wall, abs(lb - la)


INSIDE_RES_M = 0.1      # Rasterweite für die Hausfläche
INSIDE_GAP_M = 3.0      # Öffnungen bis zu dieser Breite (Fenster, Türen, Garagentor) gelten als zu
CLUSTER_GAP_M = 3.0     # Wände mit kleineren Abständen gehören zu einer Gruppe (Haus statt Grenzmauer)
INSIDE_POINT_M = 1.0    # um Messpunkte und Fundorte: Dort war jemand, die Stelle liegt im Haus
OUTLINE_CLOSE_M = 0.4   # Vorschlag im Editor: Lücken bis 2 × 0,4 m schließen (Innenwände)
OUTLINE_SIMPLIFY_M = 0.2   # Vorschlag im Editor: Umriss bis auf diese Abweichung vereinfachen


def _disk(rad: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rad + 1, 2 * rad + 1))


def _link_parts(la: int, lb: int):
    """t-Abschnitte der Strecke je Stockwerk zwischen den Ebenen la und lb."""
    za, zb = la * FLOOR_HEIGHT_M + DEVICE_HEIGHT_M, lb * FLOOR_HEIGHT_M + DEVICE_HEIGHT_M
    for lvl in range(min(la, lb), max(la, lb) + 1):
        ta = (lvl * FLOOR_HEIGHT_M - za) / (zb - za)
        tb = ((lvl + 1) * FLOOR_HEIGHT_M - za) / (zb - za)
        t0, t1 = max(0.0, min(ta, tb)), min(1.0, max(ta, tb))
        if t1 > t0:
            yield lvl, t0, t1


def _interior(floor: Floor, use_outline: bool = True) -> dict:
    """Hausfläche als Raster (Zellen von INSIDE_RES_M): {inside, source, f (Bildpixel je Zelle), pad}.

    Hat der Anwender Umrisse gezeichnet (Floor.outline), gelten sie (source "outline"). Sonst rollt eine
    Kugel mit INSIDE_GAP_M Durchmesser von außen heran; was sie nicht erreicht, liegt innen. Fenster und
    Türen bis zu dieser Breite halten sie auf. Bleibt dabei weniger als die Hälfte der konvexen Hülle der
    größten Wandgruppe übrig (Außenwände nicht gezeichnet, z. B. unter Dachschrägen), zählt die Hülle; sie
    umfasst dann auch Messpunkte und Fundorte des Stockwerks. Um Messpunkte und Fundorte zählt immer ein
    Kreis mit INSIDE_POINT_M als innen: Dort hat jemand gemessen oder ein Gerät gefunden.
    Wandflächen zählen nie mit."""
    f = INSIDE_RES_M * floor.scale.px_per_m      # Bildpixel je Rasterzelle
    r = INSIDE_GAP_M / 2 / INSIDE_RES_M         # Kugelradius in Zellen
    pad = int(r) + 3                            # Rand, damit die Kugel ums Haus rollen kann
    h, w = math.ceil(floor.image_h / f) + 2 * pad, math.ceil(floor.image_w / f) + 2 * pad
    mask = np.zeros((h, w), np.uint8)
    for wl in floor.walls:
        L = math.dist(wl.a, wl.b) or 1.0
        nx, ny = -(wl.b[1] - wl.a[1]) / L * wl.thickness_px / 2, (wl.b[0] - wl.a[0]) / L * wl.thickness_px / 2
        poly = np.array([[wl.a[0] + nx, wl.a[1] + ny], [wl.b[0] + nx, wl.b[1] + ny],
                         [wl.b[0] - nx, wl.b[1] - ny], [wl.a[0] - nx, wl.a[1] - ny]]) / f + pad
        cv2.fillConvexPoly(mask, np.rint(poly).astype(np.int32), 1)
    free = mask == 0
    out = {"f": f, "pad": pad, "walls": mask}
    if use_outline and floor.outline:
        user = np.zeros_like(mask)
        for pg in floor.outline:
            cv2.fillPoly(user, [np.rint(np.asarray(pg, float) / f + pad).astype(np.int32)], 1)
        return {**out, "inside": free & (user > 0), "source": "outline"}
    pts = np.array([[p.pos[0] / f + pad, p.pos[1] / f + pad] for p in [*floor.survey, *floor.found]]).reshape(-1, 2)
    dist = cv2.distanceTransform(free.astype(np.uint8), cv2.DIST_L2, 5)
    _, lab = cv2.connectedComponents((dist > r).astype(np.uint8), connectivity=4)
    edge = np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]])
    reach = np.isin(lab, np.unique(edge[edge > 0])).astype(np.uint8)
    inside = free & (cv2.dilate(reach, _disk(math.ceil(r))) == 0)
    source, hull = "walls", None
    if mask.any():
        grown = cv2.dilate(mask, _disk(int(CLUSTER_GAP_M / 2 / INSIDE_RES_M)))
        n, cl = cv2.connectedComponents(grown, connectivity=8)
        sizes = np.bincount(cl[mask > 0], minlength=n)
        sizes[0] = 0
        ys, xs = np.nonzero((cl == sizes.argmax()) & (mask > 0))
        wall_pts = np.stack([xs, ys], axis=1)
        hull = np.zeros_like(mask)
        cv2.fillConvexPoly(hull, cv2.convexHull(wall_pts.astype(np.int32)), 1)
        if inside.sum() < 0.5 * (free & (hull > 0)).sum():
            source = "hull"
            if len(pts):   # Außenwände fehlen: Wo gemessen oder gefunden wurde, reicht das Haus mindestens hin
                cv2.fillConvexPoly(hull, cv2.convexHull(np.concatenate([wall_pts, pts]).astype(np.int32)), 1)
            inside = free & (hull > 0)
    core = inside
    if len(pts):
        near = np.zeros_like(mask)
        for x, y in pts:
            cv2.circle(near, (int(x), int(y)), round(INSIDE_POINT_M / INSIDE_RES_M), 1, -1)
        inside = inside | (free & (near > 0))
    return {**out, "inside": inside, "source": source, "core": core, "hull": hull if source == "hull" else None}


def _contours(it: dict, region: np.ndarray, eps_cells: float) -> list[list[list[float]]]:
    """Außenkonturen einer Rasterfläche als Umrisse in Bildpixeln (vereinfacht um eps_cells)."""
    f, pad = it["f"], it["pad"]
    contours, _ = cv2.findContours(region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [[[round(float((x - pad + 0.5) * f), 1), round(float((y - pad + 0.5) * f), 1)]
             for x, y in cv2.approxPolyDP(c, eps_cells, True).reshape(-1, 2)]
            for c in contours if cv2.contourArea(c) * INSIDE_RES_M ** 2 >= 1.0]


def interior_mask(floor: Floor, ppm: float, gx: np.ndarray, gy: np.ndarray) -> tuple[np.ndarray, dict]:
    """Rasterpunkte (Bildpixel gx, gy) innerhalb des Hauses und der Umriss der gezählten Fläche (siehe _interior)."""
    it = _interior(floor)
    inside, f, pad = it["inside"], it["f"], it["pad"]
    outline = [[list(p) for p in pg] for pg in floor.outline] if it["source"] == "outline" else _contours(it, inside, 1.0)
    h, w = inside.shape
    ix = np.clip((gx / f).astype(int) + pad, 0, w - 1)
    iy = np.clip((gy / f).astype(int) + pad, 0, h - 1)
    return inside[iy, ix], {"source": it["source"], "outline": outline}


def outline_proposal(floor: Floor) -> dict:
    """Vorschlag für die Hausfläche im Editor: die automatisch bestimmte Fläche als wenige, glatte Umrisse.

    Ohne die Kreise um Messpunkte (sie machen den Umriss wellig). Innenwände werden geschlossen, die Fläche
    zerfällt sonst in einzelne Räume. Fehlen die Außenwände, ist der Vorschlag die Hülle um Wände und Messpunkte."""
    it = _interior(floor, use_outline=False)
    if it["hull"] is not None:
        region = it["hull"]
    else:
        region = cv2.morphologyEx(it["core"].astype(np.uint8), cv2.MORPH_CLOSE, _disk(round(OUTLINE_CLOSE_M / INSIDE_RES_M)))
    return {"source": it["source"], "polygons": _contours(it, region, OUTLINE_SIMPLIFY_M / INSIDE_RES_M)}


def _measurement_index(m: dict):
    cell_ap, ap_info = {}, {}
    for ap in m.get("access_points", []):
        key = f"ap:{norm_mac(ap.get('mac'))}"
        ap_info[key] = ap
        for c in ap.get("cells", []):
            cell_ap[norm_mac(c["bssid"])] = (key, ap["name"], c.get("band"))
    name_key = {ap["name"]: k for k, ap in ap_info.items()}
    shellys = {}
    for s in m.get("shellys", []):
        mac = norm_mac((s.get("id") or "")[-12:])
        if len(mac) == 12:
            shellys[mac] = s
    clients = {norm_mac(c.get("mac")): c for c in m.get("clients", [])}
    return cell_ap, ap_info, name_key, shellys, clients


class _Names:
    """Namen und Stockwerke der platzierten Zugangspunkte (für Texte)."""

    def __init__(self, project: Project, ap_info: dict):
        self.ap_info = ap_info
        self.label = {d.key: d.label for f in project.floors for d in f.devices if d.kind == "ap"}
        self.floor_of = {d.key: f.name for f in project.floors for d in f.devices}

    def ap(self, key: str) -> str:
        return self.label.get(key) or (self.ap_info.get(key) or {}).get("name") or key


def _measured(d, idx, names: _Names) -> dict:
    """Messwerte eines platzierten Geräts aus dem Messlauf."""
    cell_ap, _, name_key, shellys, clients = idx
    mac = d.key.split(":", 1)[1]
    entry = {"id": d.id, "key": d.key, "label": d.label, "kind": d.kind, "pos": d.pos,
             "connected": None, "best": None, "scan": {}, "sticky": False}
    if d.kind == "shelly" and mac in shellys:
        s = shellys[mac]
        st = s.get("status") or {}
        c = cell_ap.get(norm_mac(st.get("bssid")))
        if c and valid_rssi(st.get("rssi")):
            entry["connected"] = {"ap": c[0], "ap_name": names.ap(c[0]), "band": c[2], "rssi": st["rssi"]}
        for n in s.get("scan") or []:
            c2 = cell_ap.get(norm_mac(n.get("bssid")))
            if c2 and valid_rssi(n.get("rssi")) and (c2[0] not in entry["scan"] or n["rssi"] > entry["scan"][c2[0]]):
                entry["scan"][c2[0]] = n["rssi"]
        if entry["connected"]:  # der eigene Zugangspunkt fehlt oft im Scan
            k0 = entry["connected"]["ap"]
            entry["scan"][k0] = max(entry["scan"].get(k0, -999), entry["connected"]["rssi"])
        others = {k: v for k, v in entry["scan"].items() if not entry["connected"] or k != entry["connected"]["ap"]}
        if others:
            kb = max(others, key=others.get)
            entry["best"] = {"ap": kb, "ap_name": names.ap(kb), "rssi": others[kb]}
            if entry["connected"] and others[kb] - entry["connected"]["rssi"] >= STICKY_DB:
                entry["sticky"] = True
    elif mac in clients:
        c = clients[mac]
        key = name_key.get(c.get("ap"))
        band = "5" if "5G" in (c.get("cell") or "") else "2.4" if "2G" in (c.get("cell") or "") else None
        if key and valid_rssi(c.get("rcpi")):
            entry["connected"] = {"ap": key, "ap_name": names.ap(key), "band": band, "rssi": c["rcpi"]}
    if entry["connected"]:
        entry["connected"]["rating"] = rating(entry["connected"]["rssi"])
        entry["connected"]["ap_floor"] = names.floor_of.get(entry["connected"]["ap"])
    return entry


def _signals(entry: dict) -> dict[str, float]:
    """Messwerte je Zugangspunkt, die zum Eichen taugen (2,4 GHz, beim Gerät oder am Zugangspunkt)."""
    if entry["kind"] == "shelly":
        return dict(entry["scan"])
    c = entry["connected"]
    return {c["ap"]: c["rssi"]} if c and c["band"] == "2.4" else {}


def _solve(X, y, w, mu, sd, bounds: dict[int, tuple[float, float]]) -> np.ndarray:
    """Gewichtete kleinste Quadrate mit Vorgaben (Mittelwert, Streuung) und Grenzen für einzelne Werte."""
    fixed: dict[int, float] = {}
    th = np.array(mu, float)
    for _ in range(len(bounds) + 1):
        A = np.vstack([X * np.sqrt(w)[:, None] / NOISE_DB, np.diag(1 / sd)])
        b = np.concatenate([y * np.sqrt(w) / NOISE_DB, mu / sd])
        for j, v in fixed.items():
            b = b - A[:, j] * v
        free = [j for j in range(X.shape[1]) if j not in fixed]
        th = np.zeros(X.shape[1])
        th[free] = np.linalg.lstsq(A[:, free], b, rcond=None)[0]
        for j, v in fixed.items():
            th[j] = v
        out = {j: float(np.clip(th[j], *lim)) for j, lim in bounds.items()
               if j not in fixed and not lim[0] <= th[j] <= lim[1]}
        if not out:
            break
        fixed.update(out)
    return th


def fit_building(samples: list[dict], ap_keys: list[str], prior: dict | None = None) -> dict:
    """P0 je Zugangspunkt, Wandfaktor k und Deckendämpfung C aus allen Messpunkten.

    prior: abweichende Vorgaben (Mittelwerte "p0" je Zugangspunkt, "k", "c", "up"; Streuungen "p0_sd", "k_sd",
    "c_sd", "up_sd"), etwa für 5 GHz aus dem 2,4-GHz-Modell."""
    prior = prior or {}
    use = [s for s in samples if s["used"]]
    na = len(ap_keys)
    col = {k: i for i, k in enumerate(ap_keys)}
    X = np.zeros((len(use), na + 3))
    y = np.zeros(len(use))
    for i, s in enumerate(use):
        X[i, col[s["ap"]]] = 1.0
        X[i, na] = -s["wall_start"]
        X[i, na + 1] = -ceiling_factor(s["ceilings"])
        X[i, na + 2] = 1.0 if s.get("link") == "up" else 0.0
        y[i] = s["measured"] + 20 * math.log10(max(s["distance_m"], MIN_D_M))
    mu = np.array([prior.get("p0", {}).get(k, PRIOR_P0[0]) for k in ap_keys]
                  + [prior.get("k", PRIOR_K[0]), prior.get("c", PRIOR_C[0]), prior.get("up", PRIOR_UP[0])])
    sd = np.array([prior.get("p0_sd", PRIOR_P0[1])] * na
                  + [prior.get("k_sd", PRIOR_K[1]), prior.get("c_sd", PRIOR_C[1]), prior.get("up_sd", PRIOR_UP[1])])
    bounds = {na: K_RANGE, na + 1: C_RANGE}
    w = np.ones(len(use))
    th = _solve(X, y, w, mu, sd, bounds)
    for _ in range(10):  # Ausreißer schrittweise geringer gewichten
        res = y - X @ th
        w_new = np.minimum(1.0, HUBER * NOISE_DB / np.maximum(np.abs(res), 1e-9))
        if np.allclose(w_new, w, atol=1e-3):
            break
        w = w_new
        th = _solve(X, y, w, mu, sd, bounds)
    p0 = {k: float(th[col[k]]) for k in ap_keys}
    k, c, up = float(th[na]), float(th[na + 1]), float(th[na + 2])
    for s in samples:
        s["predicted"] = round(predict(p0[s["ap"]], k, c, s["distance_m"], s["wall_start"], s["ceilings"])
                               + (up if s.get("link") == "up" else 0.0), 1)
        s["wall_db"] = round(k * s["wall_start"], 1)
        s["ceiling_db"] = round(c * ceiling_factor(s["ceilings"]), 1)

    def rmse(rows):
        return round(float(np.sqrt(np.mean([(r["predicted"] - r["measured"]) ** 2 for r in rows]))), 1) if rows else None

    n_walls = sum(1 for s in use if s["wall_start"] > 1.0)
    n_ceilings = sum(1 for s in use if s["ceilings"] > 0)
    return {"p0": {key: round(v, 1) for key, v in p0.items()}, "k": round(k, 2), "c": round(c, 1),
            "up_db": round(up, 1), "n_up": sum(1 for s in use if s.get("link") == "up"),
            "n": len(use), "n_walls": n_walls, "n_ceilings": n_ceilings, "rmse": rmse(use),
            "k_at_bound": n_walls > 0 and (k <= K_RANGE[0] + 1e-6 or k >= K_RANGE[1] - 1e-6),
            "per_ap": {key: {"n": sum(1 for s in use if s["ap"] == key),
                             "rmse": rmse([s for s in use if s["ap"] == key])} for key in ap_keys}}


def band5_offset(samples5: list[dict], model: dict) -> float:
    """Abschlag 5 GHz gegenüber dem 2,4-GHz-Modell: Mittel der Abweichungen, zur Vorgabe hin gezogen.
    Getrennt vom Fit, damit 5-GHz-Werte Wandfaktor und Decke für 2,4 GHz nicht verschieben."""
    res = []
    for s in samples5:
        pred = predict(model["p0"][s["ap"]], model["k"], model["c"], s["distance_m"], s["wall_start"], s["ceilings"])
        pred += model["up_db"] if s.get("link") == "up" else 0.0
        s["predicted24"] = round(float(pred), 1)
        if s["used"]:   # einzelne Ausreißer begrenzen wie beim Fit
            res.append(float(np.clip(s["measured"] - pred, -HUBER * NOISE_DB * 2, HUBER * NOISE_DB * 2)))
    off = (sum(res) + PRIOR_5 * N0_5) / (len(res) + N0_5)
    for s in samples5:
        s["predicted"] = round(s["predicted24"] + off, 1)
    return round(off, 1)


POSITION_TEXT = {"ok": "in Ordnung", "too_close": "zu nah", "too_far": "zu weit weg"}


def mesh_uplinks(m: dict, names: _Names) -> list[dict]:
    """Anbindung der per WLAN angebundenen Repeater laut Mesh-Liste: Signal je Band in beide Richtungen
    (down: am Repeater gemessen, up: an der FRITZ!Box) und die Einschätzung von FRITZ!OS zum Platz.

    Diese Werte gehen nicht in die Eichung: Zugangspunkte empfangen einander mit anderen Antennen und anderer
    Messung als Geräte. Im Testhaus lagen sie 20 dB über (OG-Bad) bis 15 dB unter (EG-Garage, 5 GHz) dem
    Modell; die Kreuzprobe wurde damit nicht besser (Entscheidung 0006, Nachtrag)."""
    meta = {f"ap:{norm_mac(ap.get('mac'))}": ap for ap in m.get("access_points", [])}
    out: dict[str, dict] = {}
    for ml in m.get("mesh_links", []):
        src, dst = f"ap:{norm_mac(ml.get('from'))}", f"ap:{norm_mac(ml.get('to'))}"
        roles = ((meta.get(src) or {}).get("role"), (meta.get(dst) or {}).get("role"))
        if roles == ("master", "slave"):
            rep, master, direction = dst, src, "down"
        elif roles == ("slave", "master"):
            rep, master, direction = src, dst, "up"
        else:
            continue
        if not valid_rssi(ml.get("rssi")) or ml.get("band") not in ("2.4", "5", "6"):
            continue
        e = out.setdefault(rep, {"key": rep, "label": names.ap(rep), "master": master, "master_label": names.ap(master),
                                 "bands": {}, "position": (meta.get(rep) or {}).get("uplink_position") or {}})
        e["bands"].setdefault(ml["band"], {})[direction] = ml["rssi"]
    return sorted(out.values(), key=lambda e: e["label"])


def uplink_findings(uplinks: list[dict]) -> list[dict]:
    """Hinweise aus der Einschätzung von FRITZ!OS zum Platz der Repeater."""
    out = []
    for u in uplinks:
        pos = u["position"]
        if not pos:
            continue
        vals = ", ".join(f"{b} GHz {u['bands'].get(b, {}).get('down', '?')} dBm".replace(".", ",") for b in sorted(pos))
        where = "; ".join(f"{b.replace('.', ',')} GHz {POSITION_TEXT.get(v, v)}" for b, v in sorted(pos.items()))
        if any(v == "too_far" for v in pos.values()):
            out.append({"level": "warn", "text": (
                f"{u['label']}: FRITZ!OS stuft den Platz als zu weit von {u['master_label']} entfernt ein ({where}; "
                f"Signal am Repeater {vals}). Die Verbindung ist schwach und bremst alle Geräte daran; näher rücken "
                "oder per LAN anbinden.")})
        elif all(v == "too_close" for v in pos.values()):
            out.append({"level": "info", "text": (
                f"{u['label']}: FRITZ!OS stuft den Platz als zu nah an {u['master_label']} ein ({where}; Signal am "
                f"Repeater {vals}). Weiter entfernt würde er mehr Fläche versorgen; „Empfehlung berechnen“ in der "
                "Simulation sucht bessere Plätze.")})
        elif any(v != "ok" for v in pos.values()):
            out.append({"level": "info", "text": f"{u['label']}: Einschätzung von FRITZ!OS zum Platz: {where} (Signal am Repeater {vals})."})
    return out


def coverage_of(best: np.ndarray, inside: np.ndarray) -> dict | None:
    """Anteil der Hausfläche je Stufe (gut, ausreichend, schwach) und Fläche in m²."""
    if not inside.any():
        return None
    v = best[inside]
    cov = {label: round(float(np.mean(v >= limit)) * 100) for limit, label in RATINGS[:3]}
    cov["flaeche_m2"] = round(float(inside.sum()) * GRID_M * GRID_M, 1)
    return cov


def predict(p0: float, k: float, c: float, d_m, wall_start, ceilings: int):
    return p0 - 20 * np.log10(np.maximum(d_m, MIN_D_M)) - k * wall_start - c * ceiling_factor(ceilings)


def is_manual(key: str) -> bool:
    """Eigenes Gerät, vom Anwender angelegt (Planung ohne Messlauf)."""
    return key.startswith("manual:")


def evaluate_building(project: Project, m: dict | None) -> dict:
    """Gemeinsamer Teil aller Stockwerke: Gebäudesystem, Messpunkte, geeichtes Modell, Hinweise.

    Ohne Messlauf (Planung) rechnet das Modell mit den Startwerten; Messpunkte vom Handy eichen trotzdem."""
    planning = m is None
    m = m or {"timestamp": None, "access_points": [], "clients": [], "shellys": []}
    b = Building(project)
    idx = _measurement_index(m)
    names = _Names(project, idx[1])
    ap_place = {d.key: (f, d) for f in b.floors for d in f.devices if d.kind == "ap"}
    samples, samples5 = [], []   # 2,4 GHz (Fit), 5 GHz (nur Abschlag)

    def add(fr, pr, key, rssi, label, link, band, **extra):
        """link: "down" = gemessen beim Gerät, "up" = gemessen am Zugangspunkt (FRITZ!Box)."""
        if not valid_rssi(rssi) or key not in ap_place or not b.linked(ap_place[key][0], fr) or band not in ("2.4", "5"):
            return
        fa, ap = ap_place[key]
        d3, wall, n = b.link(fa, b.to_m(fa, [ap.pos])[0], fr, pr)
        (samples5 if band == "5" else samples).append({
            "ap": key, "ap_label": ap.label, "ap_floor": fa.name, "label": label, "floor": fr.name, "measured": rssi,
            "distance_m": round(float(d3[0]), 2), "wall_start": float(wall[0]), "ceilings": n,
            "used": float(d3[0]) >= FIT_MIN_D_M, "link": link, **extra})

    for fr in b.floors:
        for d in fr.devices:
            if d.kind == "ap":
                continue
            pr = b.to_m(fr, [d.pos])
            e = _measured(d, idx, names)
            for key, rssi in _signals(e).items():
                add(fr, pr, key, rssi, d.label, "down" if d.kind == "shelly" else "up", "2.4")
            c = e["connected"]
            if d.kind != "shelly" and c and c["band"] == "5":
                add(fr, pr, c["ap"], c["rssi"], d.label, "up", "5")
        # Messpunkte vom Rundgang mit dem Handy (Sicht des Handys)
        for i, sp in enumerate(fr.survey, 1):
            pr = b.to_m(fr, [sp.pos])
            for key, bands in sp.aps.items():
                for band in ("2.4", "5"):
                    if bands.get(band) is not None:
                        label = f"Messpunkt {i}" + (" (Scan am Fundort)" if sp.found else "")
                        add(fr, pr, key, bands[band], label, "down", band, survey=True)
        # Fundorte gesuchter Geräte (Sicht der FRITZ!Box bei der Suche)
        for i, fp in enumerate(fr.found, 1):
            add(fr, b.to_m(fr, [fp.pos]), fp.ap, fp.rssi, f"Fundort {i}: {fp.label or fp.device}", "up", fp.band,
                found=True)
    model = fit_building(samples, list(ap_place))
    model["n_survey"] = sum(1 for s in samples if s.get("survey") and s["used"])
    model["n_found"] = sum(1 for s in samples + samples5 if s.get("found") and s["used"])
    model["band5_db"] = band5_offset(samples5, model)
    model["n5"] = sum(1 for s in samples5 if s["used"])
    # eigenes Modell für 5 GHz; ohne 5-GHz-Werte bleibt es beim 2,4-GHz-Modell plus Abschlag
    m5 = fit_building(samples5, list(ap_place), prior={
        "p0": {k: v + model["band5_db"] for k, v in model["p0"].items()}, "k": model["k"], "c": model["c"],
        "up": model["up_db"], **PRIOR5_SD})
    model["band5"] = {k: m5[k] for k in ("p0", "k", "c", "up_db", "n", "n_ceilings", "rmse")}
    meta5 = idx[1]
    # 5-GHz-Karte nur für Zugangspunkte mit 5-GHz-Zelle; ohne Angabe im Messlauf (eigene Geräte): ja
    model["has5"] = {k: not (meta5.get(k) or {}).get("cells") or any(c.get("band") == "5" for c in meta5[k]["cells"])
                     for k in ap_place}
    model["samples"] = samples
    model["samples5"] = samples5
    model["floor_height_m"] = FLOOR_HEIGHT_M
    model["uplinks"] = mesh_uplinks(m, names)
    meta = idx[1]   # Rolle (master = FRITZ!Box, slave = Repeater) und Anbindung aus dem Messlauf
    model["aps"] = [{"key": key, "label": ap.label, "floor": fa.name, "floor_id": fa.id, "p0": model["p0"][key],
                     "role": (meta.get(key) or {}).get("role") or ap.role,
                     "uplink": ((meta.get(key) or {}).get("uplink") or {}).get("type") or ap.uplink,
                     "manual": is_manual(key), **model["per_ap"][key]}
                    for key, (fa, ap) in ap_place.items()]

    findings = []
    if planning:
        findings.append({"level": "info", "text": (
            f"Noch kein Messlauf: Die Karten rechnen mit Startwerten ({PRIOR_P0[0]:.0f} dBm in 1 m je Zugangspunkt, "
            f"Wände nach Material und Dicke, {PRIOR_C[0]:.0f} dB je Decke). Messpunkte vom Handy (Ansicht „Messen“) "
            "oder ein Messlauf mit FRITZ!Box eichen das Modell.")})
    for f in project.floors:
        if not f.scale:
            findings.append({"level": "info", "text": f"{f.name}: ohne Maßstab, wird nicht ausgewertet."})
    if len(b.floors) > 1:
        loose = [f.name for f in b.floors if not b.aligned(f)]
        if loose:
            findings.append({"level": "info", "text": (
                "Nicht ausgerichtet: " + ", ".join(loose) + ". Dort zählen nur die eigenen Zugangspunkte; "
                "Signale durch die Decken fehlen. Ansicht „Ausrichten“ öffnen.")})
        if model["n_ceilings"]:
            findings.append({"level": "info", "text": (
                f"Decken: Aus {model['n_ceilings']} Messpunkten über Stockwerke hinweg dämpft eine Decke etwa "
                f"{model['c']:.0f} dB (Startwert {PRIOR_C[0]:.0f} dB für 20 cm Stahlbeton).")})
        elif any(b.aligned(f) for f in b.floors):
            findings.append({"level": "info", "text": (
                f"Decken: Noch kein Gerät misst einen Zugangspunkt eines anderen Stockwerks; gerechnet wird mit "
                f"{PRIOR_C[0]:.0f} dB je Decke.")})
    for a in model["aps"]:
        if a["n"] == 0 and model["n"] > 0:
            findings.append({"level": "info", "text": (
                f"{a['label']}: kein Gerät misst ihn (ab 1 m Abstand); die Karte rechnet mit dem Startwert "
                f"{PRIOR_P0[0]:.0f} dBm in 1 m.")})
    if model["k_at_bound"]:
        findings.append({"level": "info", "text": (
            f"Wände: Die Messwerte lassen sich kaum durch Wände erklären (Wandfaktor {model['k']:.1f}, an der "
            "Untergrenze). Die Unterschiede zwischen den Geräten (Einbauort, Antenne) sind größer als der Einfluss "
            "der Wände; die Karte hängt deshalb vor allem vom Abstand ab.")})
    findings += uplink_findings(model["uplinks"])
    missing = {}
    for f in project.floors:
        for d in f.devices:
            if d.kind == "ap":
                continue
            e = _measured(d, idx, names)
            if e["connected"] and e["connected"]["ap"] not in ap_place:
                missing.setdefault(e["connected"]["ap_name"], []).append(d.label)
    for name, devs in sorted(missing.items()):
        findings.append({"level": "info", "text": (
            f"{name} ist nicht platziert (oder das Stockwerk hat keinen Maßstab), {len(devs)} Gerät(e) hängen daran. "
            "Ohne Platz fehlt er in den Karten.")})
    return {"building": b, "index": idx, "names": names, "model": model, "findings": findings,
            "measured_at": m.get("timestamp")}


def public_model(model: dict, floor_name: str | None = None) -> dict:
    """Modell für die Oberfläche; mit Stockwerk nur dessen Messpunkte (Gerät oder Zugangspunkt dort)."""
    out = {k: v for k, v in model.items() if k not in ("samples", "samples5", "p0", "per_ap")}
    samples = model["samples"]
    if floor_name is not None:
        samples = [s for s in samples if floor_name in (s["floor"], s["ap_floor"])]
    out["samples"] = [{k: v for k, v in s.items() if k != "wall_start"} for s in samples]
    return out


def floor_grid(floor: Floor) -> tuple[float, float, float, np.ndarray, np.ndarray]:
    """Raster der Karten (GRID_M) in Bildpixeln: über Wände, Geräte, Messpunkte, Fundorte und Umriss, 1 m Rand.

    Liefert x0, y0, Zellgröße in Bildpixeln und die Mittelpunkte der Zellen (gx, gy)."""
    ppm = floor.scale.px_per_m
    pts_all = [p for w in floor.walls for p in (w.a, w.b)] + [d.pos for d in [*floor.devices, *floor.survey, *floor.found]]
    pts_all += [p for pg in floor.outline or [] for p in pg]
    if not pts_all:
        raise ValueError("Keine Wände und Geräte auf dem Stockwerk.")
    arr = np.array(pts_all, float)
    margin = 1.0 * ppm
    x0, y0 = np.maximum(arr.min(axis=0) - margin, 0)
    x1, y1 = np.minimum(arr.max(axis=0) + margin, [floor.image_w, floor.image_h])
    cell = GRID_M * ppm
    gx, gy = np.meshgrid(np.arange(x0 + cell / 2, x1, cell), np.arange(y0 + cell / 2, y1, cell))
    return float(x0), float(y0), float(cell), gx, gy


def floor_area(floor: Floor) -> dict:
    """Hausfläche des Stockwerks wie in der Auswertung: {source, area_m2} (ohne Wände)."""
    _, _, _, gx, gy = floor_grid(floor)
    inside, area = interior_mask(floor, floor.scale.px_per_m, gx, gy)
    return {"source": area["source"], "area_m2": round(float(inside.sum()) * GRID_M * GRID_M, 1)}


def evaluate_floor(project: Project, floor: Floor, m: dict | None, base: dict | None = None) -> dict:
    if not floor.scale:
        raise ValueError("Für die Auswertung braucht das Stockwerk einen Maßstab.")
    base = base or evaluate_building(project, m)
    b: Building = base["building"]
    model = base["model"]
    ppm = floor.scale.px_per_m
    devices = [_measured(d, base["index"], base["names"]) for d in floor.devices if d.kind != "ap"]

    x0, y0, cell, gx, gy = floor_grid(floor)
    grid_m = b.to_m(floor, np.stack([gx.ravel(), gy.ravel()], axis=1))

    # alle Zugangspunkte, die dieses Stockwerk erreichen: eigene zuerst, dann nach Zahl der Decken
    aps, maps, maps5 = [], {}, {}
    m5 = model["band5"]
    sources = [(fa, d) for fa in b.floors if b.linked(fa, floor) for d in fa.devices if d.kind == "ap"]
    sources.sort(key=lambda x: (abs(x[0].level - floor.level), x[0].level < floor.level, x[1].label))
    for fa, ap in sources:
        pa = b.to_m(fa, [ap.pos])[0]
        d3, wall, n = b.link(fa, pa, floor, grid_m)
        maps[ap.key] = predict(model["p0"][ap.key], model["k"], model["c"], d3, wall, n).reshape(gy.shape)
        if model["has5"].get(ap.key, True):
            maps5[ap.key] = predict(m5["p0"][ap.key], m5["k"], m5["c"], d3, wall, n).reshape(gy.shape)
        pos = ap.pos if fa.id == floor.id else [round(float(v), 1) for v in b.to_px(floor, [pa])[0]]
        aps.append({"key": ap.key, "label": ap.label, "floor": fa.name, "same_floor": fa.id == floor.id,
                    "ceilings": n, "above": fa.level > floor.level, "pos": pos})

    inside, area = interior_mask(floor, ppm, gx, gy)

    def best_of(mp: dict) -> tuple[dict | None, list]:
        """Beste Versorgung (mp["best"]), Abdeckung und Anteil der Fläche je Zugangspunkt."""
        cand = [a for a in aps if a["key"] in mp]
        if not cand:
            return None, []
        stack = np.stack([mp[a["key"]] for a in cand])
        mp["best"] = stack.max(axis=0)
        cov = coverage_of(mp["best"], inside)
        if not cov:
            return None, []
        top = np.bincount(stack.argmax(axis=0)[inside], minlength=len(cand)) / inside.sum()
        return cov, [{"key": a["key"], "label": a["label"], "floor": a["floor"], "share": round(float(x) * 100)}
                     for a, x in sorted(zip(cand, top), key=lambda t: -t[1]) if x >= 0.01]

    coverage, shares = best_of(maps)
    coverage5, shares5 = best_of(maps5)

    findings = []
    if area["source"] == "hull":
        findings.append({"level": "info", "text": (
            "Hausfläche geschätzt: Die Außenwände sind nicht durchgehend gezeichnet, gezählt wird die Fläche "
            "innerhalb der Wände (gestrichelter Umriss). Im Editor mit dem Werkzeug „Hausfläche“ (Taste H) "
            "prüfen und korrigieren.")})
    for d in sorted(devices, key=lambda d: (d["connected"] or {}).get("rssi", 0)):
        c = d["connected"]
        if not c:
            if not is_manual(d["key"]) and base["measured_at"]:
                findings.append({"level": "info", "text": f"{d['label']}: im letzten Messlauf nicht gefunden."})
            continue
        where = f" ({c['ap_floor']})" if c.get("ap_floor") and c["ap_floor"] != floor.name else ""
        if d["sticky"]:
            bst = d["best"]
            findings.append({"level": "warn", "text": (
                f"{d['label']}: {c['rssi']} dBm an {c['ap_name']}{where}, {bst['ap_name']} wäre mit {bst['rssi']} dBm "
                f"um {bst['rssi'] - c['rssi']} dB besser. Shellys wechseln erst unter −80 dBm von selbst.")})
        elif c["rating"] in ("schwach", "kritisch"):
            findings.append({"level": "warn" if c["rating"] == "schwach" else "error",
                             "text": f"{d['label']}: nur {c['rssi']} dBm an {c['ap_name']}{where} ({c['rating']})."})
    findings += base["findings"]

    names = base["names"]
    survey = []
    for i, sp in enumerate(floor.survey, 1):
        best = max(((k, band, v) for k, bands in sp.aps.items() for band, v in bands.items() if valid_rssi(v)),
                   key=lambda x: x[2], default=None)
        survey.append({"id": sp.id, "n": i, "pos": sp.pos, "t": sp.t.isoformat(), "aps": sp.aps,
                       "connected": {**sp.connected, "ap_label": names.ap(sp.connected["ap"]) if sp.connected.get("ap") else None}
                       if sp.connected else None,
                       "best": {"ap": best[0], "ap_label": names.ap(best[0]), "band": best[1], "rssi": best[2],
                                "rating": rating(best[2])} if best else None})

    grid_meta = {"x": float(x0), "y": float(y0), "cell_px": float(cell), "cols": int(gx.shape[1]), "rows": int(gx.shape[0])}
    return {"measured_at": base["measured_at"], "floor": floor.name, "px_per_m": ppm, "devices": devices,
            "aps": aps, "model": public_model(model, floor.name), "coverage": coverage, "shares": shares, "survey": survey,
            "coverage5": coverage5, "shares5": shares5,
            "area": area, "findings": findings, "grid": grid_meta, "legend": legend(), "loss_db_per_cm": LOSS_DB_PER_CM,
            "_maps": maps, "_maps5": maps5, "_grid": {"shape": gx.shape, "grid_m": grid_m, "inside": inside}}


def heatmap_png(values: np.ndarray) -> bytes:
    rgba = colorize(values)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    if not ok:
        raise ValueError("Karte ließ sich nicht erzeugen")
    return buf.tobytes()
