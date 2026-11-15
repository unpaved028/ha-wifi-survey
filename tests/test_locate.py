"""Gerät im Haus suchen: Wahrscheinlichkeit über Stockwerke, Fundort als Messpunkt, Abgleich der Sicht
der FRITZ!Box (uplink) und 5-GHz-Abschlag."""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from wifi_survey import api as api_mod
from wifi_survey import evaluate as ev
from wifi_survey import locate
from wifi_survey.api import create_app
from wifi_survey.models import Crop, FoundPoint, Placement, Project
from wifi_survey.store import Store

from .test_evaluate import PPM, floor, square

AP1, AP2 = "ap:0212379c0fb4", "ap:024ddff4447b"
BOX = {"name": "fritz.box", "mac": "02:12:37:9C:0F:B4", "role": "master",
       "cells": [{"name": "AP:2G:0", "bssid": "02:12:37:9C:0F:B7", "band": "2.4"},
                 {"name": "AP:5G:0", "bssid": "02:12:37:9C:0F:B6", "band": "5"}]}
REP = {"name": "OG-Repeater", "mac": "02:4D:DF:F4:44:7B", "role": "slave",
       "cells": [{"name": "AP:2G:0", "bssid": "02:4D:DF:F4:44:7D", "band": "2.4"}]}
AP_POS = {AP1: ((600.0, 1000.0), 0), AP2: ((1400.0, 1000.0), 1)}   # Bildpixel (1 px = 1 cm), Ebene
PHONE = (1100.0, 700.0)                                               # wirklicher Ort des Handys im EG


def rssi_at(ap, pos, level, up=0.0, c=10.0):
    (x, y), lvl = AP_POS[ap]
    d = math.hypot(math.hypot(x - pos[0], y - pos[1]) / PPM, (level - lvl) * ev.FLOOR_HEIGHT_M)
    return round(-40 - 20 * math.log10(max(d, 0.5)) - c * ev.ceiling_factor(abs(level - lvl)) + up)


def house(phone_rssi=None, extra_clients=()):
    """EG und OG (je 10 × 10 m, ausgerichtet), FRITZ!Box im EG, Repeater im OG, Shellys zum Eichen."""
    shellys, devs = [], {0: [], 1: []}
    for i, (x, y, lvl) in enumerate([(800, 600, 0), (1300, 1300, 0), (700, 1400, 0), (1200, 800, 0),
                                     (700, 700, 1), (1200, 1300, 1), (900, 1100, 1), (1350, 650, 1)]):
        mac = f"aabbccddee{i:02x}"
        scan = [{"ssid": "WLAN", "bssid": "02:12:37:9C:0F:B7", "rssi": rssi_at(AP1, (x, y), lvl)},
                {"ssid": "WLAN", "bssid": "02:4D:DF:F4:44:7D", "rssi": rssi_at(AP2, (x, y), lvl)}]
        own = max(scan, key=lambda s: s["rssi"])
        shellys.append({"ip": f"192.168.1.{20 + i}", "id": f"shellyplus1-{mac}", "gen": 2, "model": "S", "app": "Plus1",
                        "fw": "1", "status": {"rssi": own["rssi"], "bssid": own["bssid"]}, "scan": scan})
        devs[lvl].append(Placement(id=f"d{i}", key=f"shelly:{mac}", kind="shelly", label=f"S{i}", pos=(x, y)))
    clients = [{"name": "Handy", "mac": "AA:BB:CC:00:11:22", "ap": "fritz.box", "cell": "AP:2G:0",
                "rcpi": rssi_at(AP1, PHONE, 0) if phone_rssi is None else phone_rssi}, *extra_clients]
    m = {"timestamp": "2026-11-02T20:00:00+00:00", "access_points": [BOX, REP], "clients": clients, "shellys": shellys}
    eg = square(1.0)
    eg.id, eg.name = "eg", "Erdgeschoss"
    eg.devices = [Placement(id="a1", key=AP1, kind="ap", label="FRITZ!Box", pos=AP_POS[AP1][0]), *devs[0]]
    og = square(1.0)
    og.id, og.name, og.level, og.reference_floor = "og", "Obergeschoss", 1, "eg"
    for w in og.walls:
        w.id = "og_" + w.id
    og.devices = [Placement(id="a2", key=AP2, kind="ap", label="Repeater OG", pos=AP_POS[AP2][0]), *devs[1]]
    return Project(floors=[eg, og]), m


def run_locate(p, m, reading):
    base = ev.evaluate_building(p, m)
    evals = {f.id: ev.evaluate_floor(p, f, m, base) for f in p.floors}
    return base, locate.locate(base, evals, p.floors, reading)


def test_locate_ranks_floor_and_contains_true_position():
    p, m = house()
    reading = {"ap": AP1, "band": "2.4", "rssi": rssi_at(AP1, PHONE, 0)}
    base, res = run_locate(p, m, reading)
    shares = {f["id"]: f["share"] for f in res["floors"]}
    assert res["best"]["floor_id"] == "eg" and shares["eg"] > 60, shares
    assert abs(sum(shares.values()) - 100) <= 1
    assert 0 < res["area_m2"] < 100 and res["floors"][0]["id"] == "og"      # oben zuerst
    eg_out = next(f for f in res["floors"] if f["id"] == "eg")
    assert eg_out["overlay"].startswith("data:image/png;base64,") and eg_out["contours"]
    q = locate.assess(res, base["building"], p.floors, p.floors[0], PHONE)
    assert q["in_region"] and q["floor_share"] == shares["eg"] and q["estimate_floor"] == "eg"
    assert q["error_m"] is not None and q["error_m"] < 8
    # ein sehr schwaches Signal am Repeater im OG: eher weit weg vom Repeater, nicht im EG direkt darunter
    _, res2 = run_locate(p, m, {"ap": AP2, "band": "2.4", "rssi": -75})
    assert all(f["share"] >= 0 for f in res2["floors"])
    peak = res2["best"]["pos"]
    assert peak is not None and math.hypot(peak[0] - 1400, peak[1] - 1000) > 300


def test_locate_without_alignment_skips_floor_and_unknown_ap_fails():
    p, m = house()
    p.floors[1].reference_floor = None             # OG nicht ausgerichtet: FRITZ!Box erreicht es im Modell nicht
    _, res = run_locate(p, m, {"ap": AP1, "band": "2.4", "rssi": -55})
    assert [f["id"] for f in res["floors"]] == ["eg"] and res["skipped"] == ["Obergeschoss"]
    with pytest.raises(ValueError):
        run_locate(p, m, {"ap": "ap:000000000000", "band": "2.4", "rssi": -55})


def test_devices_list_marks_placed_and_reads_band():
    p, m = house(extra_clients=[{"name": "Tablet", "mac": "AA:BB:CC:00:11:33", "ap": "OG-Repeater", "cell": "AP:5G:0",
                                 "rcpi": -61}])
    m["clients"].append({"name": "shellyplus1-aabbccddee00", "mac": "AA:BB:CC:DD:EE:00", "ap": "fritz.box",
                         "cell": "AP:2G:0", "rcpi": -50})
    devs = locate.devices(m, p)
    keys = [d["key"] for d in devs]
    assert keys == ["client:aabbcc001122", "client:aabbcc001133", "shelly:aabbccddee00"]   # platzierte zuletzt
    tab = devs[1]
    assert tab["ap"] == AP2 and tab["band"] == "5" and tab["rssi"] == -61 and tab["placed"] is None
    assert devs[2]["placed"] == "Erdgeschoss" and devs[2]["label"] == "S0"


def test_fit_estimates_uplink_and_5ghz_offsets():
    # Clients (Sicht der FRITZ!Box) 5 dB stärker als die Shellys (Sicht des Geräts), 5 GHz 8 dB schwächer
    clients, devs = [], []
    for i, (x, y) in enumerate([(800, 1400), (1300, 600), (1000, 1000), (1400, 1300), (700, 900), (1200, 1200)]):
        mac = f"aabbcc0011{i:02x}"
        band5 = i >= 4
        r = rssi_at(AP1, (x, y), 0, up=5) - (8 if band5 else 0)
        clients.append({"name": f"C{i}", "mac": mac, "ap": "fritz.box", "cell": "AP:5G:0" if band5 else "AP:2G:0", "rcpi": r})
        devs.append(Placement(id=f"c{i}", key=f"client:{mac}", kind="client", label=f"C{i}", pos=(x, y)))
    p, m = house()
    m["clients"] = clients
    p.floors[0].devices += devs
    mdl = ev.evaluate_building(p, m)["model"]
    # wenige Werte: der Abgleich wird zur Vorgabe 0 dB gezogen (Streuung 6 dB), bleibt aber deutlich positiv
    assert mdl["n_up"] == 4 and 2.5 < mdl["up_db"] <= 5.5, mdl["up_db"]
    assert mdl["n5"] == 2 and -9 < mdl["band5_db"] < -6, mdl["band5_db"]
    assert abs(mdl["p0"][AP1] + 40) < 1.5      # P0 bleibt die Sicht der Geräte


@pytest.fixture()
def client_store(tmp_path, monkeypatch):
    p, m = house()
    store = Store(tmp_path / "projekt")
    store.save(p)
    (tmp_path / "messungen").mkdir()
    (tmp_path / "messungen" / "2026-11-02T200000Z.json").write_text(__import__("json").dumps(m))
    from wifi_survey import catalog, collect
    monkeypatch.setattr(catalog, "HASS_ENV", tmp_path / "fehlt.env")

    def no_fritz():
        raise RuntimeError("Kein Zugang zur FRITZ!Box eingerichtet")
    monkeypatch.setattr(collect, "snapshot", no_fritz)
    return TestClient(create_app(store)), store, m


def test_api_locate_found_and_calibration(client_store, monkeypatch):
    client, store, m = client_store
    r = client.get("/api/locate/devices")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["source"] == "messlauf" and "FRITZ!Box" in data["error"]
    assert data["devices"][0]["key"] == "client:aabbcc001122" and data["devices"][0]["placed"] is None

    r = client.post("/api/locate", json={"device": "client:aabbcc001122"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["best"]["floor_id"] == "eg" and not any(k.startswith("_") for k in res)
    assert client.post("/api/locate", json={"device": "client:ffffffffffff"}).status_code == 404

    body = {"device": "client:aabbcc001122", "label": "Handy", "pos": list(PHONE), "reading": res["reading"]}
    r = client.post("/api/floors/eg/found", json=body)
    assert r.status_code == 200, r.text
    fp = r.json()
    assert fp["in_region"] is True and fp["estimate_floor"] == "eg" and fp["error_m"] is not None
    ev_eg = client.get("/api/floors/eg/evaluation").json()
    assert ev_eg["model"]["n_found"] == 1
    assert any(s["label"] == "Fundort 1: Handy" and s["link"] == "up" for s in ev_eg["model"]["samples"])

    # gleicher Wert wie beim letzten Fundort: Hinweis bei der Suche, Rückfrage beim Speichern an anderer Stelle
    res2 = client.post("/api/locate", json={"device": "client:aabbcc001122"}).json()
    assert res2["previous"]["unchanged"] is True and res2["previous"]["floor"] == "Erdgeschoss"
    moved = {**body, "pos": [700.0, 1300.0], "reading": res2["reading"]}
    r = client.post("/api/floors/eg/found", json=moved)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "unchanged", r.text
    assert client.post("/api/floors/eg/found", json={**body, "pos": [1150.0, 700.0]}).status_code == 200  # kaum bewegt
    fp3 = client.post("/api/floors/eg/found", json={**moved, "force": True})
    assert fp3.status_code == 200
    for f in store.load().floor("eg").found[1:]:
        assert client.delete(f"/api/floors/eg/found/{f.id}").status_code == 200

    # live: frische Mesh-Liste statt Messlauf
    from wifi_survey import collect
    snap = {"timestamp": "2026-11-02T20:05:00+00:00", "access_points": m["access_points"],
            "clients": [{**m["clients"][0], "rcpi": -70}]}
    monkeypatch.setattr(collect, "snapshot", lambda: snap)
    data = client.get("/api/locate/devices?refresh=true").json()
    assert data["source"] == "live" and data["devices"][0]["rssi"] == -70 and data["error"] is None

    # Gerät umgelegt: die Suche fragt neu ab, sobald die Werte älter als 15 s sind
    snap2 = {**snap, "timestamp": "2026-11-02T20:06:00+00:00", "clients": [{**m["clients"][0], "rcpi": -58}]}
    monkeypatch.setattr(collect, "snapshot", lambda: snap2)
    assert client.post("/api/locate", json={"device": "client:aabbcc001122"}).json()["reading"]["rssi"] == -70  # noch frisch
    t_now = api_mod.time.time()
    monkeypatch.setattr(api_mod.time, "time", lambda: t_now + 20)
    r = client.post("/api/locate", json={"device": "client:aabbcc001122"}).json()
    assert r["reading"]["rssi"] == -58 and r["reading"]["measured_at"] == "2026-11-02T20:06:00+00:00"

    assert client.delete(f"/api/floors/eg/found/{fp['id']}").json() == {"ok": True}
    assert store.load().floor("eg").found == []
    assert client.delete(f"/api/floors/eg/found/{fp['id']}").status_code == 404


def test_reproject_moves_found_points():
    f = floor("f", 0)
    f.found = [FoundPoint(id="x", pos=(100, 100), device="client:aabbcc001122", ap=AP1, rssi=-60)]
    api_mod._reproject(f, Crop(x=0, y=0, w=2000, h=2000), 1.0, Crop(x=50, y=50, w=1000, h=1000), 2.0)
    assert f.found[0].pos == (100.0, 100.0)    # (100 − 50) · 2
    assert np.isfinite(f.found[0].pos).all()
