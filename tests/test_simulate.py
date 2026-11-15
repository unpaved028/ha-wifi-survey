"""Simulation und Empfehlung auf einem kleinen Haus mit zwei Stockwerken."""

import math

from wifi_survey import evaluate as ev
from wifi_survey import simulate as sim
from wifi_survey.models import (
    Crop,
    Floor,
    Placement,
    Project,
    Scale,
    SimulationRequest,
    Transform,
    Wall,
)

PPM = 100.0
BOX, REP = "ap:0212379c0fb4", "ap:024ddff4447b"


def box_floor(fid, level, devices, ref=None):
    """Haus 12 × 8 m (Außenwände 24 cm), Bild 1600 × 1200 px, 1 px = 1 cm."""
    o, w, h = 200.0, 1200.0, 800.0
    walls = [Wall(id=f"{fid}{i}", a=a, b=b, thickness_px=24) for i, (a, b) in enumerate(
        [((o, o), (o + w, o)), ((o + w, o), (o + w, o + h)), ((o + w, o + h), (o, o + h)), ((o, o + h), (o, o))])]
    return Floor(id=fid, name=fid, level=level, plan_id="p", crop=Crop(x=0, y=0, w=1600, h=1200), render_scale=1.0,
                 image_w=1600, image_h=1200, scale=Scale(a=(0, 0), b=(PPM, 0), length_m=1.0), walls=walls,
                 devices=devices, transform=Transform(), reference_floor=ref)


def scene(mesh_links=None):
    box = Placement(id="b", key=BOX, kind="ap", label="FRITZ!Box", pos=(300, 600))
    rep = Placement(id="r", key=REP, kind="ap", label="Repeater", pos=(400, 600))   # schlecht: neben der Box
    shellys, eg_dev = [], []
    for i, x in enumerate((900, 1100, 1300)):
        mac = f"aabbccddee{i:02x}"
        d = math.dist((300, 600), (x, 600)) / PPM
        shellys.append({"id": f"shellyplus1-{mac}", "status": {"rssi": round(-40 - 20 * math.log10(d)),
                                                               "bssid": "02:12:37:9c:0f:b7"}, "scan": []})
        eg_dev.append(Placement(id=f"d{i}", key=f"shelly:{mac}", kind="shelly", label=f"S{i}", pos=(x, 600)))
    m = {"timestamp": "2026-10-30T09:00:00+00:00", "clients": [], "shellys": shellys,
         "access_points": [
             {"name": "fritz.box", "role": "master", "mac": "02:12:37:9C:0F:B4", "uplink": None,
              "cells": [{"name": "AP:2G:0", "bssid": "02:12:37:9C:0F:B7", "band": "2.4"}]},
             {"name": "Repeater", "role": "slave", "mac": "02:4D:DF:F4:44:7B", "uplink": {"type": "WLAN"},
              "cells": [{"name": "AP:2G:0", "bssid": "02:4D:DF:F4:44:7D", "band": "2.4"}],
              "uplink_position": {"2.4": "too_close"}}],
         "mesh_links": mesh_links or []}
    eg = box_floor("eg", 0, [box, rep, *eg_dev])
    og = box_floor("og", 1, [], ref="eg")
    p = Project(floors=[eg, og])
    base = ev.evaluate_building(p, m)
    evals = {f.id: ev.evaluate_floor(p, f, m, base) for f in (eg, og)}
    return sim.Scene(base, evals)


def test_simulation_moves_switches_off_and_adds():
    sc = scene()
    unchanged = sc.simulate(SimulationRequest(floor_id="eg"))
    assert unchanged["score"]["before"] == unchanged["score"]["after"] and unchanged["devices"] == []
    moved = sc.simulate(SimulationRequest(floor_id="eg", moved={REP: {"floor_id": "eg", "pos": (1100, 600)}}))
    assert moved["score"]["after"] > moved["score"]["before"]
    eg = next(f for f in moved["floors"] if f["id"] == "eg")
    assert eg["after"]["gut"] >= eg["before"]["gut"]
    assert moved["devices"] and moved["devices"][0]["delta"] > 0 and moved["devices"][0]["after_ap"] == "Repeater"
    rep = next(a for a in moved["floor"]["aps"] if a["key"] == REP)
    assert rep["moved"] and rep["orig"] == [400, 600] and rep["moved_m"] == 7.0
    assert moved["uplinks"] and moved["uplinks"][0]["label"] == "Repeater"
    assert moved["floor"]["map"].startswith("data:image/png;base64,")
    # im OG erscheint der Repeater als Zugangspunkt von unten
    og = sc.simulate(SimulationRequest(floor_id="og", moved={REP: {"floor_id": "eg", "pos": (1100, 600)}}))
    assert all(not a["same_floor"] and not a["above"] for a in og["floor"]["aps"])
    off = sc.simulate(SimulationRequest(floor_id="eg", off=[BOX]))
    assert off["warnings"] and any(a.get("off") for a in off["floor"]["aps"])
    new = sc.simulate(SimulationRequest(floor_id="eg", added=[{"id": "x", "floor_id": "eg", "pos": (1200, 600)}]))
    assert any(a["new"] for a in new["floor"]["aps"]) and new["score"]["after"] > new["score"]["before"]


def test_recommend_moves_repeater_towards_weak_side():
    sc = scene()
    rec = sc.recommend([REP])
    assert rec["score"]["after"] > rec["score"]["before"]
    x, _ = rec["moved"][REP]["pos"]
    assert x > 700, rec      # weg von der Box, Richtung der schwachen Geräte
    # Die Box kommt am neuen Platz noch gut genug an (WLAN-Anbindung)
    rep = sc.resolve(SimulationRequest(moved=rec["moved"]))
    assert sc.uplink(next(a for a in rep if a.key == REP), rep)[0] >= sim.UPLINK_MIN_DBM
    rec2 = sc.recommend([], add=1)
    assert len(rec2["added"]) == 1 and rec2["score"]["after"] > rec2["score"]["before"]


def test_uplink_starts_from_measured_value():
    move = {REP: {"floor_id": "eg", "pos": (1100, 600)}}
    plain = scene().simulate(SimulationRequest(floor_id="eg", moved=move))
    model_new = plain["uplinks"][0]["rssi"]
    assert plain["uplinks"][0]["basis"] == "model"
    # gemessen: Der Repeater empfängt die FRITZ!Box 10 dB stärker, als das Modell an seinem Platz sagt
    sc0 = scene()
    at_rep, basis = sc0.uplink(sc0.aps[REP], list(sc0.aps.values()))
    assert basis == "model"
    links = [{"from": "02:12:37:9C:0F:B4", "to": "02:4D:DF:F4:44:7B", "band": "2.4", "rssi": round(at_rep) + 10},
             {"from": "02:4D:DF:F4:44:7B", "to": "02:12:37:9C:0F:B4", "band": "2.4", "rssi": round(at_rep) + 4}]
    sc = scene(links)
    now, basis = sc.uplink(sc.aps[REP], list(sc.aps.values()))
    assert basis == "measured" and now == round(at_rep) + 10                                  # heute: der Messwert
    moved = sc.simulate(SimulationRequest(floor_id="eg", moved=move))
    u = moved["uplinks"][0]
    assert u["basis"] == "calibrated" and abs(u["rssi"] - (model_new + 10)) <= 1, moved["uplinks"]


def test_uplinks_and_fritzos_assessment():
    links = [{"from": "02:12:37:9C:0F:B4", "to": "02:4D:DF:F4:44:7B", "band": "2.4", "rssi": -30},
             {"from": "02:4D:DF:F4:44:7B", "to": "02:12:37:9C:0F:B4", "band": "2.4", "rssi": -35},
             {"from": "02:4D:DF:F4:44:7B", "to": "02:12:37:9C:0F:B4", "band": "5", "rssi": 0}]   # ungültig
    m = {"access_points": [{"name": "fritz.box", "role": "master", "mac": "02:12:37:9C:0F:B4"},
                           {"name": "Repeater", "role": "slave", "mac": "02:4D:DF:F4:44:7B",
                            "uplink_position": {"2.4": "too_close"}}],
         "mesh_links": links}
    names = ev._Names(Project(), {f"ap:{ev.norm_mac(a['mac'])}": a for a in m["access_points"]})
    ups = ev.mesh_uplinks(m, names)
    assert ups == [{"key": REP, "label": "Repeater", "master": BOX, "master_label": "fritz.box",
                    "bands": {"2.4": {"down": -30, "up": -35}}, "position": {"2.4": "too_close"}}]
    f = ev.uplink_findings(ups)
    assert len(f) == 1 and "zu nah an fritz.box" in f[0]["text"] and "2,4 GHz -30 dBm" in f[0]["text"], f
    ups[0]["position"] = {"2.4": "ok", "5": "too_far"}
    assert ev.uplink_findings(ups)[0]["level"] == "warn"
    ups[0]["position"] = {"2.4": "ok"}
    assert ev.uplink_findings(ups) == []


def test_manual_access_points_keep_role_and_uplink():
    box = Placement(id="b", key="manual:aa11", kind="ap", label="Router", pos=(300, 600), role="master")
    rep = Placement(id="r", key="manual:bb22", kind="ap", label="Repeater", pos=(500, 600), role="slave", uplink="WLAN")
    eg = box_floor("eg", 0, [box, rep])
    p = Project(floors=[eg])
    base = ev.evaluate_building(p, None)
    sc = sim.Scene(base, {"eg": ev.evaluate_floor(p, eg, None, base)})
    assert sc.master.key == "manual:aa11" and sc.aps["manual:bb22"].uplink == "WLAN"
    moved = sc.simulate(SimulationRequest(floor_id="eg", moved={"manual:bb22": {"floor_id": "eg", "pos": (1200, 600)}}))
    assert moved["uplinks"][0]["label"] == "Repeater" and moved["uplinks"][0]["basis"] == "model"
