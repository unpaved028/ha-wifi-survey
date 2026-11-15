"""Beispielhaus (Paket A17): ein erzeugtes Einfamilienhaus mit zwei Stockwerken zum Ausprobieren.

Der Plan ist ein Bild mit beiden Stockwerken nebeneinander, wie ein eingescannter Bauplan. Dazu kommen Wände mit
Material, Router und Repeater, Messpunkte vom Handy, benannte Räume und ein Messlauf wie von der FRITZ!Box mit
Geräten, die man suchen kann. Die Messwerte rechnet das Ausbreitungsmodell mit festen Werten aus (TRUE_24, TRUE_5),
dazu eine feste Streuung. So haben Eichung, Karten, Simulation, Empfehlung und Suche etwas zu tun, ohne fremde Daten.

Laden geht nur in ein leeres Projekt (api.py). Im Beispiel fragt die App weder FRITZ!Box noch Shellys ab
(Project.demo), „Beispiel beenden“ leert das Projekt wieder.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import cv2
import numpy as np

from . import evaluate as ev
from .models import Crop, Floor, Placement, Project, RoomLabel, Scale, SurveyPoint, Wall

PPM = 50.0                  # Bildpixel je Meter im Planbild
W_M, H_M = 12.0, 9.0        # Grundfläche je Stockwerk
PAD_M = 1.5                 # Rand um jedes Stockwerk im Planbild
EXT, INT, LIGHT = 0.365, 0.175, 0.125   # Wanddicken in Metern: außen, tragend innen, leicht
SEED = 17
NOISE_DB = 3.5              # Streuung der erzeugten Messwerte
HEARD_DB = -90              # schwächer erscheint ein Zugangspunkt nicht im Scan
SURVEY_STEP_M = 2.0         # Abstand der Messpunkte in einem Raum
MEASUREMENT_SUFFIX = "-beispiel.json"

FLOORS = [("eg", "Erdgeschoss", 0), ("og", "Obergeschoss", 1)]
Z = "hochlochziegel"
TB = "trockenbau"
# Wände je Stockwerk in Metern (Mittellinie): x0, y0, x1, y1, Dicke, Material. Lücken sind Türen (0,8–1 m).
WALLS = {
    "eg": [
        (0, 0, 12, 0, EXT, Z), (12, 0, 12, 9, EXT, Z), (0, 0, 0, 9, EXT, Z),
        (0, 9, 6, 9, EXT, Z), (7, 9, 12, 9, EXT, Z),                                   # Haustür bei 6–7 m
        (0, 5, 5.0, 5, INT, Z), (5.9, 5, 7.9, 5, INT, Z), (8.8, 5, 11.0, 5, INT, Z), (11.8, 5, 12, 5, INT, Z),
        (7.5, 0, 7.5, 1.0, INT, Z), (7.5, 1.9, 7.5, 5, INT, Z),
        (4, 5, 4, 6.5, LIGHT, TB), (4, 7.4, 4, 9, LIGHT, TB),
        (9, 5, 9, 6.0, LIGHT, TB), (9, 6.8, 9, 9, LIGHT, TB),
        (10.5, 5, 10.5, 9, LIGHT, TB),
    ],
    "og": [
        (0, 0, 12, 0, EXT, Z), (12, 0, 12, 9, EXT, Z), (0, 9, 12, 9, EXT, Z), (0, 0, 0, 9, EXT, Z),
        (0, 5, 4.5, 5, INT, Z), (5.4, 5, 6.5, 5, INT, Z), (7.4, 5, 12, 5, INT, Z),
        (6, 0, 6, 5, LIGHT, TB),
        (4, 5, 4, 6.2, LIGHT, TB), (4, 7.0, 4, 9, LIGHT, TB),
        (8, 5, 8, 6.2, LIGHT, TB), (8, 7.1, 8, 9, LIGHT, TB),
    ],
}
# Räume: Name und Rechteck (x0, y0, x1, y1) in Metern; die App erkennt sie selbst aus den Wänden, hier nur die Namen
ROOMS = {
    "eg": [("Wohnen", (0, 0, 7.5, 5)), ("Küche", (7.5, 0, 12, 5)), ("Arbeiten", (0, 5, 4, 9)), ("Flur", (4, 5, 9, 9)),
           ("WC", (9, 5, 10.5, 9)), ("Abstellraum", (10.5, 5, 12, 9))],
    "og": [("Schlafen", (0, 0, 6, 5)), ("Kinderzimmer", (6, 0, 12, 5)), ("Bad", (0, 5, 4, 9)), ("Flur oben", (4, 5, 8, 9)),
           ("Büro", (8, 5, 12, 9))],
}
# Zugangspunkte: Stockwerk, Name im Messlauf, Bezeichnung im Plan, Rolle, Platz (m), Modell
APS = [
    ("eg", "fritz.box", "FRITZ!Box", "master", (0.8, 8.3), "FRITZ!Box (Beispiel)"),
    ("og", "Repeater", "Repeater Flur", "slave", (6.0, 6.2), "Repeater (Beispiel)"),
]
# WLAN-Geräte: Stockwerk, Name, Platz (m), im Plan platziert? Die übrigen kann man in „Suchen“ suchen.
CLIENTS = [
    ("eg", "Fernseher", (0.5, 2.5), True), ("eg", "Drucker", (3.4, 8.5), True),
    ("eg", "Lautsprecher Küche", (11.5, 0.6), True), ("og", "Laptop", (10.5, 7.5), True),
    ("og", "Handy Lena", (9.5, 2.5), False), ("eg", "Tablet", (4.0, 1.5), False), ("og", "Handy Max", (1.5, 1.8), False),
]
# „wahre“ Ausbreitung im Beispiel: P0 je Rolle, Wandfaktor, Decke, Abgleich für die Sicht des Zugangspunkts
TRUE_24 = {"p0": {"master": -36.0, "slave": -38.0}, "k": 1.0, "c": 13.0, "up": -4.0}
TRUE_5 = {"p0": {"master": -43.0, "slave": -45.0}, "k": 1.5, "c": 17.0, "up": -5.0}


def _mac(group: int, i: int) -> str:
    """Lokal verwaltete MAC-Adressen (02:…): kommen in echten Geräten nicht vor."""
    return f"02:00:00:00:{group:02x}:{i:02x}"


def _key(kind: str, mac: str) -> str:
    return f"{kind}:{mac.replace(':', '')}"


def floor_size_px() -> tuple[float, float]:
    return (W_M + 2 * PAD_M) * PPM, (H_M + 2 * PAD_M) * PPM


def plan_image() -> np.ndarray:
    """Grundriss als Graustufenbild: Wände schwarz gefüllt, beide Stockwerke nebeneinander, darunter der Name."""
    fw, fh = floor_size_px()
    img = np.full((round(fh) + 30, round(fw * len(FLOORS))), 255, np.uint8)
    for i, (fid, name, _) in enumerate(FLOORS):
        ox, oy = i * fw + PAD_M * PPM, PAD_M * PPM
        for x0, y0, x1, y1, t, _m in WALLS[fid]:
            h = t * PPM / 2
            a = (round(ox + min(x0, x1) * PPM - h), round(oy + min(y0, y1) * PPM - h))
            b = (round(ox + max(x0, x1) * PPM + h), round(oy + max(y0, y1) * PPM + h))
            cv2.rectangle(img, a, b, 0, -1)
        cv2.putText(img, name.upper(), (round(ox), round(oy + H_M * PPM + PAD_M * PPM * 0.75 + 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, 60, 1, cv2.LINE_AA)
    return img


def floors(plan_id: str, new_id: Callable[[str], str]) -> list[Floor]:
    """Stockwerke als Ausschnitte des Planbilds; das Rendern übernimmt api.py."""
    fw, fh = floor_size_px()
    return [Floor(id=new_id("f"), name=name, level=level, plan_id=plan_id, page=0,
                  crop=Crop(x=i * fw, y=0, w=fw, h=fh), render_scale=1.0, image_w=1, image_h=1)
            for i, (_, name, level) in enumerate(FLOORS)]


def fill(project: Project, demo_floors: list[Floor], new_id: Callable[[str], str]) -> dict:
    """Maßstab, Wände, Geräte, Raumnamen und Messpunkte eintragen; liefert den Messlauf (wie von der FRITZ!Box)."""
    rng = np.random.default_rng(SEED)
    by_fid = dict(zip([f for f, _, _ in FLOORS], demo_floors, strict=True))
    base = demo_floors[0]

    def px(fid: str, p) -> tuple[float, float]:
        ppm = PPM * by_fid[fid].render_scale
        return round((PAD_M + p[0]) * ppm, 1), round((PAD_M + p[1]) * ppm, 1)

    for fid, f in by_fid.items():
        ppm = PPM * f.render_scale
        f.scale = Scale(a=px(fid, (0, -0.6)), b=px(fid, (W_M, -0.6)), length_m=W_M)
        f.walls = [Wall(id=new_id("w"), a=px(fid, (x0, y0)), b=px(fid, (x1, y1)), thickness_px=round(t * ppm, 2),
                        material=m, source="manual") for x0, y0, x1, y1, t, m in WALLS[fid]]
        f.room_labels = [RoomLabel(pos=px(fid, ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)), name=n) for n, r in ROOMS[fid]]
        if f is not base:
            f.reference_floor = base.id      # gleiche Lage: Stockwerke liegen ohne Verschiebung übereinander

    aps = []
    for i, (fid, name, label, role, pos, model) in enumerate(APS):
        mac = _mac(0, i + 1)
        aps.append({"fid": fid, "name": name, "role": role, "pos": pos, "key": _key("ap", mac), "measurement": {
            "name": name, "role": role, "model": model, "mac": mac, "uplink": None,
            "cells": [{"name": "AP:2G:0", "bssid": _mac(1, 2 * i + 1), "ssid": "Beispiel", "channel": 6, "band": "2.4"},
                      {"name": "AP:5G:0", "bssid": _mac(1, 2 * i + 2), "ssid": "Beispiel", "channel": 36 + 16 * i, "band": "5"}]}})
        by_fid[fid].devices.append(Placement(id=new_id("d"), key=_key("ap", mac), kind="ap", label=label, pos=px(fid, pos)))
    clients = []
    for j, (fid, name, pos, placed) in enumerate(CLIENTS):
        mac = _mac(2, j + 1)
        clients.append((fid, name, pos, mac))
        if placed:
            by_fid[fid].devices.append(Placement(id=new_id("d"), key=_key("client", mac), kind="client", label=name,
                                                 pos=px(fid, pos)))

    b = ev.Building(project)

    def predict(ap: dict, fid: str, pos, band: str, up: bool = False) -> float:
        tr = TRUE_5 if band == "5" else TRUE_24
        fa, fr = by_fid[ap["fid"]], by_fid[fid]
        pa = b.to_m(fa, [px(ap["fid"], ap["pos"])])[0]
        d3, wall, n = b.link(fa, pa, fr, b.to_m(fr, [px(fid, pos)]))
        v = ev.predict(tr["p0"][ap["role"]], tr["k"], tr["c"], d3, wall, n)[0]
        return float(v) + (tr["up"] if up else 0.0) + float(rng.normal(0, NOISE_DB))

    # Messpunkte vom Handy (Sicht des Handys): in jedem Raum ein Raster, an Wänden und Türen vorbei
    for fid, f in by_fid.items():
        for _, (x0, y0, x1, y1) in ROOMS[fid]:
            xs = np.arange(x0 + 0.8, x1 - 0.5, SURVEY_STEP_M)
            ys = np.arange(y0 + 0.8, y1 - 0.5, SURVEY_STEP_M)
            pts = [(float(x), float(y)) for x in xs for y in ys] or [((x0 + x1) / 2, (y0 + y1) / 2)]
            for p in pts:
                vals = {ap["key"]: {bd: round(predict(ap, fid, p, bd)) for bd in ("2.4", "5")} for ap in aps}
                vals = {k: {bd: v for bd, v in bands.items() if v >= HEARD_DB} for k, bands in vals.items()}
                vals = {k: bands for k, bands in vals.items() if bands}
                best = max(((k, bd, v) for k, bands in vals.items() for bd, v in bands.items()), key=lambda t: t[2], default=None)
                f.survey.append(SurveyPoint(id=new_id("s"), pos=px(fid, p), aps=vals, device="Beispiel-Handy",
                                            connected={"ap": best[0], "band": best[1], "rssi": best[2]} if best else None))

    # Messlauf: Sicht der Zugangspunkte auf die Geräte (wie die Mesh-Liste der FRITZ!Box)
    m_clients = []
    for fid, name, pos, mac in clients:
        cand = [(ap, bd, predict(ap, fid, pos, bd, up=True)) for ap in aps for bd in ("5", "2.4")]
        five = [c for c in cand if c[1] == "5" and c[2] >= -72]
        ap, bd, v = max(five or cand, key=lambda c: c[2])
        m_clients.append({"name": name, "mac": mac, "ap": ap["name"], "cell": "AP:5G:0" if bd == "5" else "AP:2G:0",
                          "rcpi": round(v), "rate_rx": 0, "rate_max": 0})
    master = next(a for a in aps if a["role"] == "master")
    for ap in aps:
        if ap["role"] == "slave":
            ap["measurement"]["uplink"] = {"type": "WLAN", "rate_rx": 0,
                                           "rcpi": round(predict(master, ap["fid"], ap["pos"], "5", up=True))}
    project.demo = True
    return {"version": 1, "timestamp": datetime.now(UTC).isoformat(timespec="seconds"), "scan": False, "demo": True,
            "access_points": [a["measurement"] for a in aps], "clients": m_clients, "shellys": [], "shelly_candidates": []}


def measurement_name() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ") + MEASUREMENT_SUFFIX
