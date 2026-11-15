"""Gerät im Haus suchen (Ansicht „Suchen“), Entscheidung 0009.

Die FRITZ!Box kennt für jedes WLAN-Gerät nur den Zugangspunkt, an dem es hängt, und das Signal, mit
dem dieser es empfängt. Für eine echte Triangulation fehlen die Werte der übrigen Zugangspunkte. Das
geeichte Modell sagt aber für jede Stelle im Haus voraus, mit welchem Signal der Zugangspunkt ein Gerät
dort empfinge. Daraus entsteht eine Wahrscheinlichkeit je Rasterzelle über alle Stockwerke:

    P(Stelle) ∝ exp(−½·((gemessen − vorhergesagt) / σ)²) · P(Gerät bleibt an diesem Zugangspunkt | Stelle)

- σ: Streuung des Modells, mindestens SIGMA_MIN_DB, bei 5 GHz etwas mehr (eigenes 5-GHz-Modell, sonst nur Abschlag).
- Vorhergesagt: Karte des Zugangspunkts plus Abgleich für die Sicht der FRITZ!Box (up_db) und ggf. 5 GHz.
- Wahl des Zugangspunkts: Geräte wechseln erst, wenn ein anderer deutlich besser ist. Stellen, an denen
  ein anderer Zugangspunkt viel stärker wäre, werden unwahrscheinlicher (logistisch, ASSOC_*).
- Nur Stellen im Haus (Hausfläche der Auswertung) zählen.

Mit dem Hintergrundmodus „findbar“ (Entscheidung 0010) liegt oft ein eigener Scan des Handys vor; dann rechnet
locate_scan mit allen Zugangspunkten (echte Triangulation).

Der „wahrscheinliche Bereich“ ist die kleinste Fläche mit REGION_MASS der Wahrscheinlichkeit. Wird das
Gerät gefunden, speichert die Ansicht den Fundort mit dem Signal der Suche (models.FoundPoint). Er geht
als Messpunkt in die Eichung ein; dazu wird festgehalten, wie gut die Schätzung lag.
"""

from __future__ import annotations

import base64

import cv2
import numpy as np

from . import evaluate as ev
from . import rooms as rooms_io
from .catalog import norm_mac
from .models import Floor, FoundPoint, Project
from .survey import valid_rssi

SIGMA_MIN_DB = 8.0          # Kreuzprobe 03.11.2026: FRITZ!Box-Werte an bekannten Stellen weichen um ~8 dB ab
SIGMA_5_EXTRA_DB = 3.0      # 5 GHz nur mit Abschlag (keine 5-GHz-Karte, z. B. alte Auswertung)
SIGMA_5_MODEL_DB = 1.0      # 5 GHz mit eigenem Modell: Kreuzprobe 7,3 dB gegenüber 6,9 dB im Modell
ASSOC_MARGIN_DB = 6.0      # bis zu diesem Vorsprung eines anderen Zugangspunkts bleibt ein Gerät oft hängen
ASSOC_SLOPE_DB = 3.0
REGION_MASS = 0.5
ROOMS_SHOWN = 8            # so viele Räume nennt die Suche höchstens (Entscheidung 0014)
ROOM_MIN_SHARE = 1         # Räume unter 1 % nicht nennen
COLOR_RGB = (123, 44, 191)  # violett, unterscheidet sich von der Signalkarte (grün bis rot)


def band_of_cell(cell: str | None) -> str | None:
    """Band aus dem Namen der Funkzelle in der Mesh-Liste (z. B. „AP:5G:0“)."""
    c = cell or ""
    return "5" if "5G" in c else "2.4" if "2G" in c else "6" if "6G" in c else None


def devices(snap: dict, project: Project) -> list[dict]:
    """WLAN-Geräte der Mesh-Liste mit Zugangspunkt, Band und Signal; platzierte mit ihrem Stockwerk.
    Nicht platzierte (Handys, Tablets, Laptops) zuerst."""
    _, ap_info, name_key, _, _ = ev._measurement_index(snap)
    placed = {d.key: f.name for f in project.floors for d in f.devices}
    labels = {d.key: d.label for f in project.floors for d in f.devices}
    out = []
    for c in snap.get("clients", []):
        mac = norm_mac(c.get("mac"))
        ap = name_key.get(c.get("ap"))
        if len(mac) != 12 or not ap or not valid_rssi(c.get("rcpi")):
            continue
        key = f"shelly:{mac}" if f"shelly:{mac}" in placed else f"client:{mac}"
        out.append({"key": key, "label": labels.get(key) or c.get("name") or mac, "ap": ap,
                    "ap_label": labels.get(ap) or ap_info[ap].get("name") or ap, "band": band_of_cell(c.get("cell")),
                    "rssi": int(c["rcpi"]), "placed": placed.get(key)})
    return sorted(out, key=lambda d: (d["placed"] is not None, d["label"].lower()))


def _png(dens: np.ndarray, vmax: float) -> str:
    rgba = np.zeros((*dens.shape, 4), np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = COLOR_RGB
    a = np.power(np.clip(dens / vmax, 0, 1), 0.6) * 215 if vmax > 0 else np.zeros(dens.shape)
    rgba[..., 3] = np.where(dens > 0, np.maximum(a, 18), 0).astype(np.uint8)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    if not ok:
        raise ValueError("Karte ließ sich nicht erzeugen")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _cell_px(g: dict, row: int, col: int) -> list[float]:
    return [round(g["x"] + (col + 0.5) * g["cell_px"], 1), round(g["y"] + (row + 0.5) * g["cell_px"], 1)]


def _contours(region: np.ndarray, g: dict) -> list[list[list[float]]]:
    cs, _ = cv2.findContours(region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        c = cv2.approxPolyDP(c, 0.8, True)
        if len(c) >= 3:
            out.append([_cell_px(g, int(p[0][1]), int(p[0][0])) for p in c])
    return out


def locate(base: dict, evals: dict[str, dict], floors: list[Floor], reading: dict) -> dict:
    """Wahrscheinlichkeit je Stelle für ein Gerät, das am Zugangspunkt reading["ap"] mit reading["rssi"]
    empfangen wird. evals: Auswertung je Stockwerk (mit _maps und _grid)."""
    model = base["model"]
    key, band, rssi = reading["ap"], reading.get("band"), float(reading["rssi"])
    high = band in ("5", "6")
    m5 = model.get("band5")
    own5 = high and m5 is not None and all(key in (evals.get(f.id) or {}).get("_maps5", {}) for f in floors
                                           if key in (evals.get(f.id) or {}).get("_maps", {}))
    if own5:   # eigenes 5-GHz-Modell (Entscheidung 0005, Nachtrag)
        sigma = max(m5.get("rmse") or ev.NOISE_DB, SIGMA_MIN_DB) + SIGMA_5_MODEL_DB
        offset = m5["up_db"]
    else:
        sigma = max(model.get("rmse") or ev.NOISE_DB, SIGMA_MIN_DB) + (SIGMA_5_EXTRA_DB if high else 0.0)
        offset = model.get("up_db", 0.0) + (model.get("band5_db", ev.PRIOR_5) if high else 0.0)
    dens, skipped = {}, []
    for f in floors:
        e = evals.get(f.id)
        if e is None or key not in e["_maps"]:
            skipped.append(f.name)   # ohne Auswertung oder nicht mit dem Zugangspunkt ausgerichtet
            continue
        maps = e["_maps5"] if own5 else e["_maps"]
        like = np.exp(-0.5 * ((rssi - (maps[key] + offset)) / sigma) ** 2)
        others = [v for k, v in maps.items() if k not in ("best", key)]
        if others:
            margin = maps[key] - np.max(others, axis=0)
            like = like / (1.0 + np.exp(-(margin + ASSOC_MARGIN_DB) / ASSOC_SLOPE_DB))
        dens[f.id] = np.where(e["_grid"]["inside"], like, 0.0)
    res = _summarize(dens, evals, floors,
                     "Zu diesem Signal passt keine Stelle im Haus (Zugangspunkt nicht platziert oder keine Hausfläche).")
    return {"reading": {"ap": key, "band": band, "rssi": int(rssi), "measured_at": reading.get("measured_at")},
            "sigma_db": round(sigma, 1), "offset_db": round(offset, 1), "skipped": skipped, "scan": None, **res}


def _summarize(dens: dict[str, np.ndarray], evals: dict[str, dict], floors: list[Floor], empty: str) -> dict:
    """Normieren über alle Stockwerke, Bereich mit REGION_MASS, Karte und Umriss je Stockwerk."""
    total = sum(float(d.sum()) for d in dens.values())
    if not total > 0:
        raise ValueError(empty)
    dens = {fid: d / total for fid, d in dens.items()}
    vals = np.sort(np.concatenate([d[d > 0] for d in dens.values()]))[::-1]
    thr = float(vals[min(int(np.searchsorted(np.cumsum(vals), REGION_MASS)), len(vals) - 1)])
    vmax = float(vals[0])

    out, area = [], 0.0
    for f in floors:
        if f.id not in dens:
            continue
        d, g = dens[f.id], evals[f.id]["grid"]
        region = (d >= thr) & (d > 0)
        r, c = np.unravel_index(int(np.argmax(d)), d.shape)
        a = float(region.sum()) * ev.GRID_M * ev.GRID_M
        area += a
        out.append({"id": f.id, "name": f.name, "level": f.level, "share": round(float(d.sum()) * 100),
                    "area_m2": round(a, 1), "peak": _cell_px(g, int(r), int(c)) if d.max() > 0 else None,
                    "overlay": _png(d, vmax), "contours": _contours(region, g), "grid": g})
    best = max(out, key=lambda x: x["share"])
    return {"region_mass": REGION_MASS, "area_m2": round(area, 1),
            "best": {"floor_id": best["id"], "floor": best["name"], "share": best["share"], "pos": best["peak"]},
            "floors": sorted(out, key=lambda x: -x["level"]), "_dens": dens, "_thr": thr}


# eigener Scan: Sicht des Handys wie beim Rundgang. Kreuzprobe an 40 Messpunkten (Testhaus, 04.11.2026, jeder ohne
# sich selbst geeicht): mit 6 dB lagen nur 15 im 50-%-Bereich, mit 8 dB 23 (Fehler im Median 2,95 statt 3,15 m)
SIGMA_SCAN_MIN_DB = 8.0
SCAN_TAU_DB = 8.0         # gemeinsame Abweichung aller Werte eines Scans (Hülle, Tasche, Decke über dem Handy)


def locate_scan(base: dict, evals: dict[str, dict], floors: list[Floor], report: dict, reading: dict) -> dict:
    """Wahrscheinlichkeit je Stelle aus dem eigenen Scan des Handys (Hintergrundmodus „findbar“, Entscheidung 0010):
    alle Zugangspunkte auf beiden Bändern, Sicht des Handys. Eine gemeinsame Abweichung aller Werte (Handy unter
    einer Decke, in der Tasche) wird herausgerechnet: Kovarianz σ²·I + τ²·11ᵀ, es zählen vor allem die Unterschiede
    zwischen den Zugangspunkten. reading: Wert der FRITZ!Box (für die Anzeige und den Fundort)."""
    model = base["model"]
    s0 = max(model.get("rmse") or ev.NOISE_DB, SIGMA_SCAN_MIN_DB)
    b5 = model.get("band5_db", ev.PRIOR_5)
    m5 = model.get("band5")
    s5 = max((m5 or {}).get("rmse") or ev.NOISE_DB, SIGMA_SCAN_MIN_DB) + SIGMA_5_MODEL_DB
    vals = [(k, b, float(v)) for k, bands in report.get("aps", {}).items() for b, v in bands.items()
            if k in model["p0"] and b in ("2.4", "5") and valid_rssi(v)]
    if not vals:
        raise ValueError("Der Scan des Handys enthält keinen platzierten Zugangspunkt.")
    logs, skipped = {}, []
    for f in floors:
        e = evals.get(f.id)
        if e is None or any(k not in e["_maps"] for k, _, _ in vals):
            skipped.append(f.name)   # ohne Auswertung oder nicht mit allen Zugangspunkten ausgerichtet
            continue
        s1 = s2 = w = 0.0
        for k, b, v in vals:
            if b == "5" and k in e.get("_maps5", {}):      # eigenes 5-GHz-Modell
                s, r = s5, v - e["_maps5"][k]
            else:
                s = s0 + (SIGMA_5_EXTRA_DB if b == "5" else 0.0)
                r = v - (e["_maps"][k] + (b5 if b == "5" else 0.0))
            s1, s2, w = s1 + r / s ** 2, s2 + r * r / s ** 2, w + 1.0 / s ** 2
        ll = -0.5 * (s2 - SCAN_TAU_DB ** 2 * s1 * s1 / (1.0 + SCAN_TAU_DB ** 2 * w))
        logs[f.id] = np.where(e["_grid"]["inside"], ll, -np.inf)
    top = max((float(np.max(x)) for x in logs.values()), default=-np.inf)
    if not np.isfinite(top):
        raise ValueError("Zum Scan des Handys passt keine Stelle im Haus (keine Hausfläche).")
    res = _summarize({fid: np.exp(x - top) for fid, x in logs.items()}, evals, floors,
                     "Zum Scan des Handys passt keine Stelle im Haus.")
    return {"reading": {"ap": reading["ap"], "band": reading.get("band"), "rssi": int(reading["rssi"]),
                        "measured_at": reading.get("measured_at")},
            "sigma_db": round(s0, 1), "offset_db": None, "skipped": skipped,
            "scan": {"t": report["t"], "n": len(vals)}, **res}


def add_rooms(result: dict, rooms_by_floor: dict[str, dict], floors: list[Floor]) -> dict:
    """Wahrscheinlichkeit je Raum (Entscheidung 0014): „rooms“ für die Liste, je Stockwerk die Räume für die Karte."""
    ranking = rooms_io.ranking(result["_dens"], rooms_by_floor, {f.id: f.name for f in floors})
    result["_rooms"], result["_room_ranking"] = rooms_by_floor, ranking
    result["rooms"] = [r for r in ranking if r["share"] >= ROOM_MIN_SHARE][:ROOMS_SHOWN]
    share = {r["key"]: r["share"] for r in ranking}
    for fl in result["floors"]:
        rb = rooms_by_floor.get(fl["id"]) or {"rooms": []}
        fl["rooms"] = [{"id": rm["id"], "name": rm["name"], "anchor": rm["anchor"], "contours": rm["contours"],
                        "share": share.get(f"{fl['id']}:{rm['id']}", 0)} for rm in rb["rooms"]]
    return result


def assess(result: dict, building: ev.Building, floors: list[Floor], floor: Floor, pos) -> dict:
    """Wie gut lag die Schätzung für einen Fundort? Für FoundPoint (estimate_floor, floor_share,
    in_region, error_m, room_rank)."""
    by_id = {f.id: f for f in floors}
    best = result["best"]
    out = {"estimate_floor": best["floor_id"], "floor_share": 0, "in_region": False, "error_m": None}
    key = rooms_io.room_key_at(result.get("_rooms") or {}, floor, pos)
    out["room_rank"] = next((r["rank"] for r in result.get("_room_ranking", []) if r["key"] == key), None)
    fl = next((x for x in result["floors"] if x["id"] == floor.id), None)
    if fl is not None:
        out["floor_share"] = fl["share"]
        g, d = fl["grid"], result["_dens"][floor.id]
        col, row = int((pos[0] - g["x"]) // g["cell_px"]), int((pos[1] - g["y"]) // g["cell_px"])
        if 0 <= row < d.shape[0] and 0 <= col < d.shape[1]:
            out["in_region"] = bool(d[row, col] >= result["_thr"] and d[row, col] > 0)
    bf = by_id.get(best["floor_id"])
    if bf is not None and best["pos"] is not None and floor.scale and bf.scale and building.linked(bf, floor):
        a, b = building.to_m(bf, [best["pos"]])[0], building.to_m(floor, [pos])[0]
        dz = (bf.level - floor.level) * ev.FLOOR_HEIGHT_M
        out["error_m"] = round(float(np.sqrt(((a - b) ** 2).sum() + dz * dz)), 1)
    return out


MOVED_M = 2.0   # weiter weg als beim letzten Fundort: das Gerät wurde umgelegt


def last_found(project: Project, device: str) -> tuple[Floor, FoundPoint] | None:
    """Letzter gemeldeter Fundort eines Geräts (über alle Stockwerke)."""
    pts = [(f, fp) for f in project.floors for fp in f.found if fp.device == device]
    return max(pts, key=lambda x: x[1].t) if pts else None


def unchanged(fp: FoundPoint, reading: dict) -> bool:
    """Gleicher Wert wie beim Fundort? Ruhende Geräte erneuert die FRITZ!Box nur alle paar Minuten."""
    return (fp.ap, fp.band, fp.rssi) == (reading["ap"], reading.get("band"), int(reading["rssi"]))


def distance_m(building: ev.Building, fa: Floor, pa, fb: Floor, pb) -> float | None:
    """Abstand zweier Stellen im Gebäude (mit Geschosshöhe); None, wenn die Stockwerke nicht verbunden sind."""
    if not (fa.scale and fb.scale and building.linked(fa, fb)):
        return None
    a, b = building.to_m(fa, [pa])[0], building.to_m(fb, [pb])[0]
    dz = (fa.level - fb.level) * ev.FLOOR_HEIGHT_M
    return float(np.sqrt(((a - b) ** 2).sum() + dz * dz))


def public(result: dict) -> dict:
    return {k: v for k, v in result.items() if not k.startswith("_")}
