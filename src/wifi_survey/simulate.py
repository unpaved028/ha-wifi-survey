"""Simulation und Empfehlung: Zugangspunkte virtuell verschieben, abschalten oder ergänzen.

Grundlage ist das geeichte Modell der Auswertung (Entscheidung 0005); Details in Entscheidung 0006.
- Ein verschobener Zugangspunkt behält sein P0. Ein neuer Repeater bekommt den Median der
  vorhandenen Repeater (ohne Repeater den Startwert).
- Geräte: Liegt ein Messwert vor, wird er um die Änderung des Modells verschoben (Messwert +
  Modell neu − Modell alt). So bleibt der Einfluss von Einbauort und Antenne erhalten. Ohne
  Messwert zählt der Modellwert.
- Bewertung einer Aufstellung: je Punkt 0 bei −80 dBm, 1 ab −60 dBm, dazwischen linear.
  Hausfläche (Raster 1 m) und Geräte zählen je zur Hälfte.
- Empfehlung: Koordinatensuche. Nacheinander für jeden verschiebbaren Zugangspunkt den besten
  Platz auf seinem Stockwerk suchen (Raster 1 m, dann 0,2 m um den besten Punkt), bis sich nichts
  mehr verbessert. Repeater mit WLAN-Anbindung nur dort, wo die FRITZ!Box laut Modell mit
  mindestens −65 dBm ankommt.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass, replace

import numpy as np

from . import evaluate as ev
from .models import Floor, SimulationRequest

UTIL_LOW, UTIL_HIGH = -80.0, -60.0
UPLINK_MIN_DBM = -65.0
EVAL_STEP = 5           # jede 5. Rasterzelle (1 m): Bewertungspunkte und grobes Suchraster
REFINE_M = 0.8          # Feinsuche im Umkreis um den besten groben Punkt
MIN_GAIN = 0.005        # kleinere Verbesserungen sind kein Grund, ein Gerät umzustellen
MAX_ROUNDS = 3
CACHE_SIZE = 300


def utility(rssi) -> np.ndarray:
    return np.clip((np.asarray(rssi, float) - UTIL_LOW) / (UTIL_HIGH - UTIL_LOW), 0.0, 1.0)


@dataclass
class Ap:
    key: str
    label: str
    floor: Floor
    pos_px: tuple[float, float]
    pos_m: tuple[float, float]
    p0: float
    role: str | None = None      # master (FRITZ!Box), slave (Repeater), None (neu)
    uplink: str | None = None    # WLAN, LAN oder None (unbekannt)


class Scene:
    """Auswertungsstand aller Stockwerke, vorbereitet für Simulation und Suche."""

    def __init__(self, base: dict, floor_evals: dict[str, dict]):
        b = self.b = base["building"]
        model = base["model"]
        self.k, self.c = model["k"], model["c"]
        ap_info = base["index"][1]
        self.floors = {f.id: f for f in b.floors if f.id in floor_evals}
        self.aps: dict[str, Ap] = {}
        for f in self.floors.values():
            for d in f.devices:
                if d.kind == "ap" and d.key in model["p0"]:
                    info = ap_info.get(d.key) or {}    # eigene Zugangspunkte: Rolle und Anbindung aus dem Plan
                    self.aps[d.key] = Ap(d.key, d.label, f, tuple(d.pos), tuple(b.to_m(f, [d.pos])[0]),
                                         model["p0"][d.key], info.get("role") or d.role,
                                         (info.get("uplink") or {}).get("type") or d.uplink)
        rep = [a.p0 for a in self.aps.values() if a.role == "slave"]
        self.new_p0 = float(np.median(rep)) if rep else ev.PRIOR_P0[0]
        self.fl: dict[str, dict] = {}
        for fid, f in self.floors.items():
            e = floor_evals[fid]
            g = e["_grid"]
            rows, cols = g["shape"]
            sub = np.zeros((rows, cols), bool)
            sub[EVAL_STEP // 2::EVAL_STEP, EVAL_STEP // 2::EVAL_STEP] = True
            devs = e["devices"]
            meas: dict[str, np.ndarray] = {}
            for i, d in enumerate(devs):
                for key, v in ev._signals(d).items():
                    meas.setdefault(key, np.full(len(devs), np.nan))[i] = v
            self.fl[fid] = {"floor": f, "shape": (rows, cols), "grid_m": g["grid_m"], "inside": g["inside"],
                            "eval_m": g["grid_m"].reshape(rows, cols, 2)[g["inside"] & sub],
                            "inside_m": g["grid_m"][g["inside"].ravel()],
                            "devices": devs, "dev_m": b.to_m(f, [d["pos"] for d in devs]) if devs else np.zeros((0, 2)),
                            "meas": meas, "before": {}, "maps0": e["_maps"]}
        for a in self.aps.values():   # Modellwerte an den Geräten bei heutiger Aufstellung
            for fl in self.fl.values():
                if b.linked(a.floor, fl["floor"]) and len(fl["dev_m"]):
                    fl["before"][a.key] = self._predict(a, [a.pos_m], fl["floor"], fl["dev_m"])[0]
        self.n_eval = sum(len(fl["eval_m"]) for fl in self.fl.values())
        self.n_dev = sum(len(fl["dev_m"]) for fl in self.fl.values())
        self.master = next((a for a in self.aps.values() if a.role == "master"), None)
        self._cache: dict = {}
        # Anbindung der Repeater: Zugangspunkte empfangen einander viel stärker als Geräte (Antennen, Messung).
        # Abgleich je Repeater = gemessenes Signal der FRITZ!Box am Repeater (Mesh-Liste, 2,4 GHz) minus Modell.
        # Am heutigen Platz gilt der Messwert, an neuen Plätzen das Modell plus der kleinste Abgleich aller
        # Repeater (vorsichtig: der Rest ist oft eine Besonderheit des Platzes). Entscheidung 0006, Nachtrag.
        self.uplink_bias: dict[str, float] = {}
        for u in model.get("uplinks", []):
            meas = (u["bands"].get("2.4") or {}).get("down")
            a, master = self.aps.get(u["key"]), self.aps.get(u["master"])
            if meas is not None and a and master and b.linked(master.floor, a.floor):
                self.uplink_bias[a.key] = meas - float(self._predict(master, [master.pos_m], a.floor, [a.pos_m])[0, 0])
        self.uplink_offset = min(self.uplink_bias.values()) if self.uplink_bias else 0.0

    # --- Rechnen ------------------------------------------------------------------------------

    def _predict(self, a: Ap, srcs, f: Floor, pts) -> np.ndarray:
        """Signal von a, gedacht an den Stellen srcs (K, auf a.floor), an den Punkten pts von f (K×N)."""
        d3, wall, n = self.b.link_many(a.floor, np.asarray(srcs, float).reshape(-1, 2), f,
                                       np.asarray(pts, float).reshape(-1, 2))
        return ev.predict(a.p0, self.k, self.c, d3, wall, n)

    def _remember(self, key, value):
        if len(self._cache) >= CACHE_SIZE:
            for old in list(self._cache)[:CACHE_SIZE // 3]:
                del self._cache[old]
        self._cache[key] = value
        return value

    def values(self, a: Ap, srcs) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """Je Stockwerk: Signal an den Bewertungspunkten (K×E) und an den Geräten (K×D)."""
        srcs = np.asarray(srcs, float).reshape(-1, 2)
        out = {}
        for fid, fl in self.fl.items():
            if not self.b.linked(a.floor, fl["floor"]):
                continue
            ne = len(fl["eval_m"])
            pv = self._predict(a, srcs, fl["floor"], np.concatenate([fl["eval_m"], fl["dev_m"]]))
            dv = pv[:, ne:]
            if a.key in fl["meas"]:   # Messwert plus Änderung des Modells
                m = fl["meas"][a.key]
                dv = np.where(np.isnan(m), dv, m + dv - fl["before"][a.key])
            out[fid] = (pv[:, :ne], dv)
        return out

    def _vals(self, a: Ap):
        key = ("vals", a.key, a.floor.id, round(a.pos_m[0], 2), round(a.pos_m[1], 2), a.p0)
        return self._cache[key] if key in self._cache else self._remember(key, self.values(a, [a.pos_m]))

    def _best(self, aps: list[Ap]):
        """Bestes Signal je Bewertungspunkt und je Gerät über alle Zugangspunkte."""
        be = {fid: np.full(len(fl["eval_m"]), -np.inf) for fid, fl in self.fl.items()}
        bd = {fid: np.full(len(fl["dev_m"]), -np.inf) for fid, fl in self.fl.items()}
        for a in aps:
            for fid, (e, d) in self._vals(a).items():
                be[fid] = np.maximum(be[fid], e[0])
                bd[fid] = np.maximum(bd[fid], d[0])
        return be, bd

    def _score(self, area_sum, dev_sum):
        area = area_sum / max(self.n_eval, 1)
        return area if not self.n_dev else 0.5 * area + 0.5 * dev_sum / self.n_dev

    def score(self, aps: list[Ap]) -> float:
        be, bd = self._best(aps)
        return float(self._score(sum(utility(v).sum() for v in be.values()), sum(utility(v).sum() for v in bd.values())))

    def full_map(self, a: Ap, fid: str) -> np.ndarray:
        """Karte eines Zugangspunkts auf dem feinen Raster eines Stockwerks."""
        fl = self.fl[fid]
        orig = self.aps.get(a.key)
        if orig and orig.floor.id == a.floor.id and orig.pos_m == a.pos_m and a.key in fl["maps0"]:
            return fl["maps0"][a.key]
        key = ("map", a.key, a.floor.id, round(a.pos_m[0], 2), round(a.pos_m[1], 2), a.p0, fid)
        if key not in self._cache:
            d3, wall, n = self.b.link(a.floor, np.array(a.pos_m), fl["floor"], fl["grid_m"])
            self._remember(key, ev.predict(a.p0, self.k, self.c, d3, wall, n).reshape(fl["shape"]))
        return self._cache[key]

    def best_map(self, aps: list[Ap], fid: str) -> np.ndarray | None:
        maps = [self.full_map(a, fid) for a in aps if self.b.linked(a.floor, self.fl[fid]["floor"])]
        return np.max(np.stack(maps), axis=0) if maps else None

    def uplink(self, a: Ap, aps: list[Ap]) -> tuple[float, str] | None:
        """Signal der FRITZ!Box am Platz eines Repeaters (2,4 GHz) und woher es stammt: "measured" (heutiger
        Platz, Mesh-Liste), "calibrated" (Modell plus Abgleich aus gemessenen Funkstrecken) oder "model"."""
        master = next((x for x in aps if x.role == "master"), None)
        if master is None or master.key == a.key or not self.b.linked(master.floor, a.floor):
            return None
        sig = float(self._predict(master, [master.pos_m], a.floor, [a.pos_m])[0, 0])
        here = self.aps.get(a.key)
        if a.key in self.uplink_bias and here and here.floor.id == a.floor.id and here.pos_m == a.pos_m \
                and self.aps.get(master.key) and self.aps[master.key].pos_m == master.pos_m:
            return sig + self.uplink_bias[a.key], "measured"
        return sig + self.uplink_offset, "calibrated" if self.uplink_bias else "model"

    # --- Aufstellung ------------------------------------------------------------------------

    def resolve(self, req: SimulationRequest) -> list[Ap]:
        out = []
        for a in self.aps.values():
            if a.key in req.off:
                continue
            mv = req.moved.get(a.key)
            if mv and mv.floor_id in self.floors:
                f = self.floors[mv.floor_id]
                out.append(replace(a, floor=f, pos_px=tuple(mv.pos), pos_m=tuple(self.b.to_m(f, [mv.pos])[0])))
            else:
                out.append(a)
        for n in req.added:
            if n.floor_id in self.floors:
                f = self.floors[n.floor_id]
                out.append(Ap(f"neu:{n.id}", n.label, f, tuple(n.pos), tuple(self.b.to_m(f, [n.pos])[0]),
                              self.new_p0, None, "WLAN"))
        return out

    def _devices(self, aps: list[Ap]) -> dict:
        """Bestes erwartetes Signal je Gerät mit Zugangspunkt."""
        out = {}
        for fid, fl in self.fl.items():
            rows, labels = [], []
            for a in aps:
                v = self._vals(a).get(fid)
                if v is not None and len(fl["dev_m"]):
                    rows.append(v[1][0])
                    labels.append(a.label)
            if not rows:
                continue
            st = np.stack(rows)
            idx = st.argmax(axis=0)
            for i, d in enumerate(fl["devices"]):
                if np.isfinite(st[idx[i], i]):
                    out[(fid, d["key"])] = (float(st[idx[i], i]), labels[idx[i]], d["label"], fl["floor"].name)
        return out

    def simulate(self, req: SimulationRequest) -> dict:
        aps0, aps1 = list(self.aps.values()), self.resolve(req)
        floors = []
        for fid, fl in sorted(self.fl.items(), key=lambda x: (x[1]["floor"].level, x[1]["floor"].name)):
            m0, m1 = self.best_map(aps0, fid), self.best_map(aps1, fid)
            floors.append({"id": fid, "name": fl["floor"].name,
                           "before": ev.coverage_of(m0, fl["inside"]) if m0 is not None else None,
                           "after": ev.coverage_of(m1, fl["inside"]) if m1 is not None else None})
        d0, d1 = self._devices(aps0), self._devices(aps1)
        devices = []
        for key, (v0, ap0, label, fname) in d0.items():
            v1, ap1 = d1.get(key, (None, None))[:2]
            if v1 is None or abs(v1 - v0) >= 1 or ap1 != ap0:
                devices.append({"label": label, "floor": fname, "before": round(v0), "before_ap": ap0,
                                "after": None if v1 is None else round(v1), "after_ap": ap1,
                                "delta": None if v1 is None else round(v1 - v0)})
        devices.sort(key=lambda d: -(d["delta"] if d["delta"] is not None else -99))
        weak = {"before": sum(1 for v in d0.values() if v[0] < -70), "after": sum(1 for v in d1.values() if v[0] < -70)}

        changed = [a for a in aps1 if a.key not in self.aps or a.pos_m != self.aps[a.key].pos_m
                   or a.floor.id != self.aps[a.key].floor.id]
        if self.master and any(a.key == self.master.key for a in changed):
            changed = [a for a in aps1 if a in changed or a.uplink == "WLAN"]
        uplinks, warnings = [], []
        for a in changed:
            if a.uplink == "WLAN":
                res = self.uplink(a, aps1)
                if res is not None:
                    uplinks.append({"label": a.label, "rssi": round(res[0]), "ok": res[0] >= UPLINK_MIN_DBM, "basis": res[1]})
            elif a.uplink == "LAN":
                warnings.append(f"{a.label} hängt per LAN: Am neuen Platz braucht er eine Netzwerkdose.")
            elif a.role == "slave":
                warnings.append(f"{a.label}: Anbindung unbekannt (LAN oder WLAN). Hängt er per LAN, braucht er am neuen "
                                "Platz eine Netzwerkdose; per WLAN muss die FRITZ!Box dort gut ankommen.")
        if self.master and self.master.key in req.off:
            warnings.append("Ohne FRITZ!Box haben die Repeater keine Verbindung ins Internet; die Karte zeigt nur die Funkversorgung.")

        out = {"floors": floors, "devices": devices, "weak_devices": weak, "uplinks": uplinks, "warnings": warnings,
               "score": {"before": round(self.score(aps0) * 100, 1), "after": round(self.score(aps1) * 100, 1)}}
        if req.floor_id in self.fl:
            out["floor"] = self._floor_view(req.floor_id, aps1, req)
        return out

    def _floor_view(self, fid: str, aps: list[Ap], req: SimulationRequest) -> dict:
        fl = self.fl[fid]
        f = fl["floor"]
        best = self.best_map(aps, fid)
        view = {"id": fid, "map": None, "aps": []}

        def here(src: Ap) -> list[float]:
            """Lage eines Zugangspunkts in Bildpixeln dieses Stockwerks."""
            if src.floor.id == fid:
                return list(src.pos_px)
            return [round(float(v), 1) for v in self.b.to_px(f, [src.pos_m])[0]]

        if best is not None:
            view["map"] = "data:image/png;base64," + base64.b64encode(ev.heatmap_png(best)).decode()
            view["coverage"] = ev.coverage_of(best, fl["inside"])
        for a in aps:
            if not self.b.linked(a.floor, f):
                continue
            orig = self.aps.get(a.key)
            item = {"key": a.key, "label": a.label, "floor": a.floor.name, "same_floor": a.floor.id == fid,
                    "above": a.floor.level > f.level, "pos": here(a),
                    "new": orig is None, "moved": bool(orig) and (orig.pos_m != a.pos_m or orig.floor.id != a.floor.id)}
            if item["moved"] and self.b.linked(orig.floor, f):
                item["orig"] = here(orig)
                item["moved_m"] = round(math.dist(orig.pos_m, a.pos_m), 1)
            view["aps"].append(item)
        for key in req.off:
            a = self.aps.get(key)
            if a and self.b.linked(a.floor, f):
                view["aps"].append({"key": key, "label": a.label, "floor": a.floor.name, "same_floor": a.floor.id == fid,
                                    "above": a.floor.level > f.level, "off": True, "pos": here(a)})
        return view

    # --- Empfehlung -------------------------------------------------------------------------

    def _allowed(self, a: Ap, others: list[Ap], fid: str, pts: np.ndarray) -> np.ndarray:
        """Kandidaten; Repeater mit WLAN-Anbindung nur, wo die FRITZ!Box gut genug ankommt."""
        master = next((x for x in others if x.role == "master"), None)
        if a.uplink != "WLAN" or master is None or not len(pts):
            return pts
        f = self.fl[fid]["floor"]
        if not self.b.linked(master.floor, f):
            return pts[:0]
        return pts[self._predict(master, [master.pos_m], f, pts)[0] + self.uplink_offset >= UPLINK_MIN_DBM]

    def _try(self, a: Ap, fid: str, cand: np.ndarray, be: dict, bd: dict):
        """Bewertung von a an jedem Kandidaten (Stockwerk fid); bester Kandidat."""
        if not len(cand):
            return None
        a2 = replace(a, floor=self.fl[fid]["floor"])
        vals = self.values(a2, cand)
        area, dev = np.zeros(len(cand)), np.zeros(len(cand))
        for f2 in self.fl:
            if f2 in vals:
                area += utility(np.maximum(be[f2][None, :], vals[f2][0])).sum(axis=1)
                dev += utility(np.maximum(bd[f2][None, :], vals[f2][1])).sum(axis=1)
            else:
                area += utility(be[f2]).sum()
                dev += utility(bd[f2]).sum()
        score = self._score(area, dev)
        i = int(np.argmax(score))
        return float(score[i]), fid, cand[i]

    def _search(self, a: Ap, others: list[Ap], floors: list[str]):
        be, bd = self._best(others)
        best = None
        for fid in floors:
            res = self._try(a, fid, self._allowed(a, others, fid, self.fl[fid]["eval_m"]), be, bd)
            if res and (best is None or res[0] > best[0]):
                best = res
        if best is None:
            return None
        fid, p = best[1], best[2]
        near = self.fl[fid]["inside_m"]
        near = near[np.linalg.norm(near - p, axis=1) <= REFINE_M]
        res = self._try(a, fid, self._allowed(a, others, fid, near), be, bd)
        if res and res[0] > best[0]:
            best = res
        score, fid, p = best
        f = self.fl[fid]["floor"]
        pos_px = tuple(round(float(v), 1) for v in self.b.to_px(f, [p])[0])
        return score, replace(a, floor=f, pos_m=(float(p[0]), float(p[1])), pos_px=pos_px)

    def _descend(self, cfg: dict[str, Ap], keys: list[str], cur: float) -> float:
        for _ in range(MAX_ROUNDS):
            changed = False
            for key in keys:
                res = self._search(cfg[key], [a for k, a in cfg.items() if k != key], [cfg[key].floor.id])
                if res and res[0] > cur + MIN_GAIN:
                    cur, cfg[key] = res[0], res[1]
                    changed = True
            if not changed:
                break
        return cur

    def recommend(self, movable: list[str], add: int = 0) -> dict:
        """Bessere Plätze für die verschiebbaren Zugangspunkte, auf Wunsch plus neue Repeater."""
        cfg = dict(self.aps)
        keys = [k for k in movable if k in cfg]
        start = self.score(list(cfg.values()))
        cur = self._descend(cfg, keys, start)
        for i in range(add):
            label = "Neuer Repeater" if add == 1 else f"Neuer Repeater {i + 1}"
            tmpl = Ap(f"neu:r{i + 1}", label, next(iter(self.floors.values())), (0.0, 0.0), (0.0, 0.0),
                      self.new_p0, None, "WLAN")
            res = self._search(tmpl, list(cfg.values()), list(self.fl))
            if res and res[0] > cur + MIN_GAIN:
                cur, cfg[tmpl.key] = res[0], res[1]
                cur = self._descend(cfg, keys + [tmpl.key], cur)
        moved = {k: a for k, a in cfg.items() if k in self.aps
                 and (a.floor.id != self.aps[k].floor.id or math.dist(a.pos_m, self.aps[k].pos_m) > 0.05)}
        added = [a for k, a in cfg.items() if k not in self.aps]
        return {"moved": {k: {"floor_id": a.floor.id, "pos": list(a.pos_px)} for k, a in moved.items()},
                "added": [{"id": a.key.split(":", 1)[1], "label": a.label, "floor_id": a.floor.id, "pos": list(a.pos_px)}
                          for a in added],
                "score": {"before": round(start * 100, 1), "after": round(cur * 100, 1)},
                "kept": [self.aps[k].label for k in keys if k not in moved]}
