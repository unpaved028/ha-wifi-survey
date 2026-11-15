"""Ausbreitungsmodell über Stockwerke: Strecken, Decken, Eichung, Hausfläche."""

import math

import numpy as np

from wifi_survey import evaluate as ev
from wifi_survey.models import (
    Crop,
    Floor,
    FoundPoint,
    Placement,
    Project,
    Scale,
    SurveyPoint,
    Transform,
    Wall,
)

PPM = 100.0   # 1 px = 1 cm


def floor(fid, level, walls=(), devices=(), ref=None, size=(2000, 2000)):
    return Floor(id=fid, name=fid, level=level, plan_id="p", crop=Crop(x=0, y=0, w=size[0], h=size[1]),
                 render_scale=1.0, image_w=size[0], image_h=size[1],
                 scale=Scale(a=(0, 0), b=(PPM, 0), length_m=1.0), walls=list(walls), devices=list(devices),
                 transform=Transform(), reference_floor=ref)


def wall(wid, x_m, y0_m=-5, y1_m=5, t_cm=24):
    return Wall(id=wid, a=(x_m * PPM, y0_m * PPM + 1000), b=(x_m * PPM, y1_m * PPM + 1000), thickness_px=t_cm)


def test_ceiling_factor():
    assert ev.ceiling_factor(0) == 0
    assert ev.ceiling_factor(1) == 1
    assert abs(ev.ceiling_factor(2) - 1.83) < 0.01 and abs(ev.ceiling_factor(3) - 2.38) < 0.01


def test_walls_count_on_the_floor_the_path_passes():
    # Strecke vom EG (x = 0 m) ins OG (x = 10 m): bis t ≈ 0,64 verläuft sie auf EG-Höhe
    eg = floor("eg", 0, walls=[wall("eg_nah", 2), wall("eg_fern", 8)])
    og = floor("og", 1, walls=[wall("og_nah", 2), wall("og_fern", 8)], ref="eg")
    b = ev.Building(Project(floors=[eg, og]))
    one = ev.LOSS_DB_PER_CM["hochlochziegel"] * 24
    src, dst = np.array([0.0, 10.0]), np.array([[10.0, 10.0]])
    d3, w, n = b.link(eg, src, og, dst)
    assert n == 1 and abs(d3[0] - math.hypot(10, ev.FLOOR_HEIGHT_M)) < 1e-9
    assert abs(w[0] - 2 * one) < 1e-6        # EG-Wand bei 2 m und OG-Wand bei 8 m
    d3, w, n = b.link(eg, src, eg, dst)
    assert n == 0 and abs(w[0] - 2 * one) < 1e-6       # im selben Stockwerk beide EG-Wände
    # nicht ausgerichtet: keine Verbindung zwischen den Stockwerken
    og2 = floor("og", 1)
    b2 = ev.Building(Project(floors=[eg, og2]))
    assert not b2.linked(eg, og2) and b2.linked(eg, eg)


def shelly(mac, rssi):
    return {"ip": "192.168.178.9", "id": f"shellyplus1-{mac}", "gen": 2, "model": "S", "app": "Plus1", "fw": "1",
            "status": {"rssi": rssi, "bssid": "02:12:37:9c:0f:b7"}, "scan": []}


def test_fit_recovers_ceiling_loss():
    # synthetische Messung: P0 −40 dBm, keine Wände, 10 dB je Decke
    def rssi(d, n):
        return round(-40 - 20 * math.log10(d) - 10 * n)
    ap = Placement(id="a", key="ap:0212379c0fb4", kind="ap", label="FRITZ!Box", pos=(500, 1000))
    eg_dev, og_dev, shellys = [], [], []
    for i, (dx, lvl) in enumerate([(2, 0), (4, 0), (6, 0), (0, 1), (3, 1), (5, 1), (7, 1)]):
        mac = f"aabbccddee{i:02x}"
        d3 = math.hypot(dx, lvl * ev.FLOOR_HEIGHT_M)
        shellys.append(shelly(mac, rssi(d3, lvl)))
        (og_dev if lvl else eg_dev).append(Placement(id=f"d{i}", key=f"shelly:{mac}", kind="shelly", label=f"S{i}",
                                                       pos=(500 + dx * PPM, 1000)))
    m = {"timestamp": "2026-10-30T08:00:00+00:00",
         "access_points": [{"name": "fritz.box", "mac": "02:12:37:9C:0F:B4",
                            "cells": [{"name": "AP:2G:0", "bssid": "02:12:37:9C:0F:B7", "band": "2.4"}]}],
         "clients": [], "shellys": shellys}
    eg = floor("eg", 0, devices=[ap, *eg_dev])
    og = floor("og", 1, devices=og_dev, ref="eg")
    p = Project(floors=[eg, og])
    base = ev.evaluate_building(p, m)
    mdl = base["model"]
    assert mdl["n"] == 7 and mdl["n_ceilings"] == 4
    assert abs(mdl["c"] - 10) < 1.5 and abs(mdl["p0"]["ap:0212379c0fb4"] + 40) < 1.5, mdl
    res = ev.evaluate_floor(p, og, m, base)
    assert set(res["_maps"]) == {"ap:0212379c0fb4", "best"}
    a = res["aps"][0]
    assert not a["same_floor"] and a["above"] is False and a["ceilings"] == 1 and a["pos"] == [500.0, 1000.0]
    # ohne Ausrichtung kommt die FRITZ!Box im OG nicht an
    og.reference_floor = None
    res = ev.evaluate_floor(Project(floors=[eg, og]), og, m)
    assert res["_maps"] == {} and any("Nicht ausgerichtet" in f["text"] for f in res["findings"])


def square(gap_m):
    """Raum 10 × 10 m (Wände 24 cm) mit einer Öffnung der Breite gap_m in der Südwand."""
    o, s = 500.0, 1000.0
    ws = [Wall(id="n", a=(o, o), b=(o + s, o), thickness_px=24), Wall(id="w", a=(o, o), b=(o, o + s), thickness_px=24),
          Wall(id="e", a=(o + s, o), b=(o + s, o + s), thickness_px=24)]
    half = (s - gap_m * PPM) / 2
    ws += [Wall(id="s1", a=(o, o + s), b=(o + half, o + s), thickness_px=24),
           Wall(id="s2", a=(o + s - half, o + s), b=(o + s, o + s), thickness_px=24)]
    return floor("f", 0, walls=ws)


def test_interior_mask_bridges_doors_and_falls_back_to_hull():
    gx, gy = np.meshgrid(np.arange(530, 1480, 20.0), np.arange(530, 1480, 20.0))
    inside, area = ev.interior_mask(square(1.0), PPM, gx, gy)
    assert area["source"] == "walls" and inside.mean() > 0.95 and area["outline"]
    inside, area = ev.interior_mask(square(8.0), PPM, gx, gy)      # Südwand fast ganz offen
    assert area["source"] == "hull" and inside.mean() > 0.95
    gx2, gy2 = np.meshgrid(np.arange(0, 400, 20.0), np.arange(0, 400, 20.0))
    inside, _ = ev.interior_mask(square(1.0), PPM, gx2, gy2)       # draußen
    assert not inside.any()


def test_interior_mask_includes_survey_points_and_found_places():
    # Dachgeschoss: nur Innenwände gezeichnet, gemessen wurde auch daneben (Dachgeschoss im Testhaus, 03.11.2026)
    f = floor("dg", 3, walls=[Wall(id="a", a=(500, 500), b=(900, 500), thickness_px=12),
                              Wall(id="b", a=(500, 500), b=(500, 900), thickness_px=12),
                              Wall(id="c", a=(900, 500), b=(900, 700), thickness_px=12)])
    gx, gy = np.meshgrid(np.arange(0, 2000, 20.0), np.arange(0, 2000, 20.0))
    at = lambda inside, x, y: bool(inside[int(y // 20), int(x // 20)])
    inside, area = ev.interior_mask(f, PPM, gx, gy)
    assert area["source"] == "hull" and not at(inside, 1300, 1300)
    f.survey = [SurveyPoint(id="s1", pos=(1300, 1300)), SurveyPoint(id="s2", pos=(1300, 600))]
    f.found = [FoundPoint(id="fd1", pos=(600, 1300), device="client:aabbccddeeff", ap="ap:1", rssi=-60)]
    inside, area = ev.interior_mask(f, PPM, gx, gy)
    assert area["source"] == "hull" and all(at(inside, x, y) for x, y in ((1300, 1300), (1300, 600), (600, 1300)))
    assert at(inside, 1000, 1000)                                  # Hülle über Wände und Punkte
    # geschlossener Raum: ein Messpunkt draußen (Balkon) zählt nur mit seinem Umkreis von 1 m
    g = square(1.0)
    g.survey = [SurveyPoint(id="s1", pos=(1800, 1000))]
    inside, area = ev.interior_mask(g, PPM, gx, gy)
    assert area["source"] == "walls" and at(inside, 1800, 1000) and at(inside, 1860, 1000) and not at(inside, 1680, 1000)


def test_outline_proposal_and_user_outline():
    g = square(1.0)
    g.walls.append(Wall(id="mid", a=(1000, 500), b=(1000, 1500), thickness_px=24))   # Innenwand teilt den Raum
    prop = ev.outline_proposal(g)
    assert prop["source"] == "walls" and len(prop["polygons"]) == 1, prop     # ein Umriss, nicht einer je Raum
    poly = np.array(prop["polygons"][0])
    assert len(poly) <= 10 and poly[:, 0].min() < 530 and poly[:, 0].max() > 1470, poly
    auto = ev.floor_area(g)
    assert auto["source"] == "walls" and 85 < auto["area_m2"] < 97, auto
    # eigener Umriss: nur die westliche Hälfte
    g.outline = [[(500, 500), (1000, 500), (1000, 1500), (500, 1500)]]
    gx, gy = np.meshgrid(np.arange(0, 2000, 20.0), np.arange(0, 2000, 20.0))
    inside, area = ev.interior_mask(g, PPM, gx, gy)
    assert area["source"] == "outline" and area["outline"] == [[[500, 500], [1000, 500], [1000, 1500], [500, 1500]]]
    assert inside[1000 // 20, 700 // 20] and not inside[1000 // 20, 1300 // 20]
    own = ev.floor_area(g)
    assert own["source"] == "outline" and 40 < own["area_m2"] < 48, own        # 5 × 10 m ohne Wände
    # Umriss über die Wände hinaus (Dachgeschoss ohne Außenwände): Raster reicht bis dorthin
    g.outline = [[(500, 500), (1900, 500), (1900, 1500), (500, 1500)]]
    assert ev.floor_area(g)["area_m2"] > own["area_m2"] + 80


def test_planning_without_measurement():
    router = Placement(id="r", key="manual:aa11", kind="ap", label="Router", pos=(500, 1000), role="master")
    rep = Placement(id="p", key="manual:bb22", kind="ap", label="Repeater", pos=(1500, 1000), role="slave", uplink="WLAN")
    tv = Placement(id="t", key="manual:cc33", kind="other", label="Fernseher", pos=(1000, 1000))
    f = square(1.0)
    f.devices = [router, rep, tv]
    p = Project(floors=[f])
    base = ev.evaluate_building(p, None)
    mdl = base["model"]
    assert mdl["n"] == 0 and mdl["p0"] == {"manual:aa11": ev.PRIOR_P0[0], "manual:bb22": ev.PRIOR_P0[0]}
    assert {a["key"]: (a["role"], a["uplink"], a["manual"]) for a in mdl["aps"]} == {
        "manual:aa11": ("master", None, True), "manual:bb22": ("slave", "WLAN", True)}
    assert any("Noch kein Messlauf" in x["text"] for x in base["findings"])
    assert not any("kein Gerät misst" in x["text"] for x in base["findings"])
    res = ev.evaluate_floor(p, f, None, base)
    assert set(res["_maps"]) == {"manual:aa11", "manual:bb22", "best"} and res["coverage"]["gut"] > 0
    assert res["measured_at"] is None and not any("nicht gefunden" in x["text"] for x in res["findings"])


def test_own_model_for_5ghz():
    # Rundgang: 2,4 GHz −40 dBm in 1 m und 8 dB je Decke, 5 GHz −47 dBm und 14 dB je Decke
    ap = Placement(id="a", key="ap:0212379c0fb4", kind="ap", label="FRITZ!Box", pos=(500, 1000))
    eg, og = floor("eg", 0, devices=[ap]), floor("og", 1, ref="eg")
    for i, (dx, lvl) in enumerate([(2, 0), (4, 0), (6, 0), (8, 0), (1, 1), (3, 1), (5, 1), (7, 1), (9, 1)]):
        d = math.hypot(dx, lvl * ev.FLOOR_HEIGHT_M)
        v24 = round(-40 - 20 * math.log10(d) - 8 * lvl)
        v5 = round(-47 - 20 * math.log10(d) - 14 * lvl)
        (og if lvl else eg).survey.append(SurveyPoint(id=f"s{i}", pos=(500 + dx * PPM, 1000),
                                                      aps={"ap:0212379c0fb4": {"2.4": v24, "5": v5}}))
    m = {"timestamp": "2026-11-04T08:00:00+00:00", "clients": [], "shellys": [],
         "access_points": [{"name": "fritz.box", "mac": "02:12:37:9C:0F:B4", "role": "master",
                            "cells": [{"name": "AP:2G:0", "bssid": "02:12:37:9C:0F:B7", "band": "2.4"},
                                      {"name": "AP:5G:0", "bssid": "02:12:37:9C:0F:B6", "band": "5"}]}]}
    p = Project(floors=[eg, og])
    base = ev.evaluate_building(p, m)
    mdl = base["model"]
    b5 = mdl["band5"]
    assert b5["n"] == 9 and abs(mdl["c"] - 8) < 2 and abs(b5["c"] - 14) < 2.5, (mdl["c"], b5)
    assert abs(b5["p0"]["ap:0212379c0fb4"] + 47) < 2 and mdl["has5"] == {"ap:0212379c0fb4": True}
    res = ev.evaluate_floor(p, og, m, base)
    assert set(res["_maps5"]) == {"ap:0212379c0fb4", "best"} and res["coverage5"] and res["shares5"]
    assert res["coverage5"]["gut"] < res["coverage"]["gut"]          # 5 GHz kommt durch die Decke schlechter an
    # Zugangspunkt ohne 5-GHz-Zelle: keine 5-GHz-Karte
    m["access_points"][0]["cells"] = m["access_points"][0]["cells"][:1]
    base = ev.evaluate_building(p, m)
    assert base["model"]["has5"] == {"ap:0212379c0fb4": False}
    res = ev.evaluate_floor(p, og, m, base)
    assert res["_maps5"] == {} and res["coverage5"] is None
