import shutil

import cv2
import pytest
from fastapi.testclient import TestClient

from wifi_survey.api import create_app, snap_thickness_px
from wifi_survey.config import PROJECT_ROOT
from wifi_survey.store import Store

from .test_walls import hatched_plan

REAL_PLAN = PROJECT_ROOT / "data" / "grundrisse" / "original" / "2019-02-19 Haus J.pdf"


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(Store(tmp_path / "projekt")))


def upload_png(client, img, name="plan.png"):
    ok, buf = cv2.imencode(".png", img)
    assert ok
    r = client.post("/api/plans", files={"file": (name, buf.tobytes(), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_flow(client):
    plan = upload_png(client, hatched_plan())
    assert plan["kind"] == "image" and plan["pages"][0]["width"] == 800

    r = client.post("/api/floors", json={"name": "Erdgeschoss", "level": 0, "plan_id": plan["id"], "page": 0,
                                         "crop": {"x": 50, "y": 50, "w": 700, "h": 500}})
    assert r.status_code == 200, r.text
    floor = r.json()
    assert (floor["image_w"], floor["image_h"]) == (700, 500)
    assert client.get(f"/api/floors/{floor['id']}/image.png").status_code == 200

    # Maßstab: obere Wand ist 600 px lang = 7,30 m  -> 82,19 px/m, 30 px = 36,5 cm
    r = client.put(f"/api/floors/{floor['id']}/scale", json={"a": [50, 64.5], "b": [650, 64.5], "length_m": 7.30})
    assert r.status_code == 200, r.text
    ppm = r.json()["scale"]["px_per_m"]
    assert abs(ppm - 600 / 7.30) < 0.01

    r = client.post(f"/api/floors/{floor['id']}/detect", json={"mode": "replace_auto", "snap_thickness": True})
    assert r.status_code == 200, r.text
    det = r.json()
    walls = det["floor"]["walls"]
    assert det["added"] == len(walls) >= 3
    long_ = [w for w in walls if abs(w["a"][0] - w["b"][0]) + abs(w["a"][1] - w["b"][1]) > 500]
    assert any(abs(w["thickness_px"] - 36.5 / 100 * ppm) < 0.05 for w in long_), long_

    # Bearbeiten: eine Wand ändern (wird manuell), eine zeichnen
    walls[0]["material"] = "stahlbeton"
    walls[0]["source"] = "manual"
    walls.append({"id": "w_neu", "a": [10, 10], "b": [10, 200], "thickness_px": 9.5, "material": "trockenbau", "source": "manual"})
    r = client.put(f"/api/floors/{floor['id']}/walls", json=walls)
    assert r.status_code == 200, r.text

    # Neue Erkennung ersetzt nur unveränderte automatische Wände – und doppelt keine bearbeiteten
    r = client.post(f"/api/floors/{floor['id']}/detect", json={"mode": "replace_auto"})
    after = r.json()["floor"]["walls"]
    ids = {w["id"] for w in after}
    assert "w_neu" in ids and walls[0]["id"] in ids
    assert len(after) == len(walls), (len(after), len(walls))
    assert r.json()["stats"]["skipped_covered"] >= 1

    # Ausschnitt verschieben: Wände und Maßstab wandern mit
    old = {w["id"]: w for w in after}
    r = client.patch(f"/api/floors/{floor['id']}", json={"crop": {"x": 40, "y": 45, "w": 700, "h": 500}})
    assert r.status_code == 200, r.text
    moved = {w["id"]: w for w in r.json()["walls"]}
    assert moved["w_neu"]["a"] == [20.0, 15.0]
    assert abs(r.json()["scale"]["px_per_m"] - ppm) < 0.01
    assert len(moved) == len(old)

    # Plan mit Stockwerken lässt sich nicht löschen
    assert client.delete(f"/api/plans/{plan['id']}").status_code == 409
    assert client.delete(f"/api/floors/{floor['id']}").status_code == 200
    assert client.delete(f"/api/plans/{plan['id']}").status_code == 200
    assert client.get("/api/project").json() == {"version": 1, "plans": [], "floors": [], "demo": False}


def test_rejects_bad_input(client):
    r = client.post("/api/plans", files={"file": ("notiz.txt", b"hallo", "text/plain")})
    assert r.status_code == 400
    plan = upload_png(client, hatched_plan())
    r = client.post("/api/floors", json={"name": "X", "plan_id": plan["id"], "crop": {"x": 0, "y": 0, "w": 5, "h": 5}})
    assert r.status_code == 400
    r = client.post("/api/floors", json={"name": "X", "plan_id": plan["id"], "crop": {"x": 0, "y": 0, "w": 100, "h": 100}})
    fid = r.json()["id"]
    bad_wall = [{"id": "w1", "a": [0, 0], "b": [1, 1], "thickness_px": 3, "material": "papier"}]
    assert client.put(f"/api/floors/{fid}/walls", json=bad_wall).status_code == 422
    dup = [{"id": "w1", "a": [0, 0], "b": [1, 1], "thickness_px": 3}] * 2
    assert client.put(f"/api/floors/{fid}/walls", json=dup).status_code == 400
    assert client.put(f"/api/floors/{fid}/scale", json={"a": [1, 1], "b": [1, 1], "length_m": 2}).status_code == 400


def test_snap_thickness():
    ppm = 83.4
    assert snap_thickness_px(29.0, ppm) == round(0.365 * ppm, 2)   # 34,8 cm -> 36,5
    assert snap_thickness_px(21.0, ppm) == round(0.24 * ppm, 2)    # 25,2 cm -> 24
    assert snap_thickness_px(80.0, ppm) == 80.0                    # 96 cm: keine Klasse in der Nähe


@pytest.mark.skipif(not REAL_PLAN.exists() or shutil.which("pdftoppm") is None, reason="Originalplan oder poppler fehlt")
def test_pdf_import_and_floor(client):
    r = client.post("/api/plans", files={"file": (REAL_PLAN.name, REAL_PLAN.read_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    plan = r.json()
    page = plan["pages"][0]
    assert page["width"] > page["height"]  # Blatt liegt quer (Seite ist gedreht)
    # Erdgeschoss: Ausschnitt in Punkt (72 dpi)
    r = client.post("/api/floors", json={"name": "Erdgeschoss", "plan_id": plan["id"],
                                         "crop": {"x": 672, "y": 648, "w": 600, "h": 948}})
    assert r.status_code == 200, r.text
    floor = r.json()
    assert abs(floor["render_scale"] - 200 / 72) < 1e-6
    r = client.post(f"/api/floors/{floor['id']}/detect", json={})
    assert r.status_code == 200
    assert r.json()["added"] > 30


def test_exterior_walls(client):
    plan = upload_png(client, hatched_plan())
    fid = client.post("/api/floors", json={"name": "EG", "plan_id": plan["id"],
                                           "crop": {"x": 0, "y": 0, "w": 800, "h": 600}}).json()["id"]
    t = 20
    walls = [
        # Außenwände eines Rechteckhauses, oben mit Fensterlücke (300..400)
        {"id": "oben_l", "a": [100, 100], "b": [300, 100], "thickness_px": t},
        {"id": "oben_r", "a": [400, 100], "b": [700, 100], "thickness_px": t},
        {"id": "unten", "a": [100, 500], "b": [700, 500], "thickness_px": t},
        {"id": "links", "a": [100, 100], "b": [100, 500], "thickness_px": t},
        {"id": "rechts", "a": [700, 100], "b": [700, 500], "thickness_px": t},
        # Innenwand gegenüber der Fensterlücke und eine Querwand
        {"id": "innen", "a": [350, 110], "b": [350, 490], "thickness_px": 10, "material": "beton"},
        {"id": "quer", "a": [110, 300], "b": [350, 300], "thickness_px": 10},
    ]
    assert client.put(f"/api/floors/{fid}/walls", json=walls).status_code == 200
    ids = set(client.get(f"/api/floors/{fid}/exterior").json()["ids"])
    assert ids == {"oben_l", "oben_r", "unten", "links", "rechts"}, ids


MEASUREMENT = {
    "version": 1, "timestamp": "2026-10-29T13:06:34+00:00", "scan": True,
    "access_points": [
        {"name": "fritz.box", "role": "master", "model": "FRITZ!Box 7590", "mac": "02:12:37:9C:0F:B4",
         "cells": [{"name": "AP:2G:0", "bssid": "02:12:37:9C:0F:B7", "ssid": "WLAN", "channel": 11, "band": "2.4"}], "uplink": None},
        {"name": "UG-Anschluss", "role": "slave", "model": "FRITZ!WLAN Repeater 1750E", "mac": "02:4D:DF:F4:44:7B",
         "cells": [{"name": "AP:2G:0", "bssid": "02:4D:DF:F4:44:7D", "ssid": "WLAN", "channel": 6, "band": "2.4"}],
         "uplink": {"type": "LAN", "rate_rx": 0, "rcpi": None}},
    ],
    "clients": [
        {"name": "shellyemminig4-021901898fdc", "mac": "02:19:01:89:8F:DC", "ap": "fritz.box", "cell": "AP:2G:0", "rcpi": -72},
        {"name": "pi", "mac": "02:53:2D:3C:F8:01", "ap": "UG-Anschluss", "cell": "AP:5G:0", "rcpi": -71},
    ],
    "shellys": [
        {"ip": "192.168.178.22", "id": "shellyemminig4-021901898fdc", "gen": 4, "model": "S4EM-001PXCEU16", "app": "MiniEMG4ZB",
         "fw": "2.0.0", "status": {"rssi": -76, "bssid": "02:12:37:9c:0f:b7"}, "scan": []},
    ],
    "shelly_candidates": 1,
}


def test_device_catalog_and_placement(client, tmp_path, monkeypatch):
    from wifi_survey import catalog
    monkeypatch.setattr(catalog, "HASS_ENV", tmp_path / "fehlt.env")   # kein Home Assistant im Test
    catalog._HA_CACHE["at"] = 0
    import json
    (tmp_path / "messungen").mkdir()
    (tmp_path / "messungen" / "2026-10-29T130634Z.json").write_text(json.dumps(MEASUREMENT))
    cat = client.get("/api/devices/catalog").json()
    keys = {d["key"]: d for d in cat["devices"]}
    assert set(keys) == {"ap:0212379c0fb4", "ap:024ddff4447b", "shelly:021901898fdc", "client:02532d3cf801"}
    assert keys["shelly:021901898fdc"]["detail"] == "S4EM-001PXCEU16, -76 dBm an fritz.box, 192.168.178.22"

    plan = upload_png(client, hatched_plan())
    f1 = client.post("/api/floors", json={"name": "EG", "plan_id": plan["id"], "crop": {"x": 0, "y": 0, "w": 400, "h": 300}}).json()["id"]
    f2 = client.post("/api/floors", json={"name": "KG", "plan_id": plan["id"], "crop": {"x": 0, "y": 0, "w": 400, "h": 300}}).json()["id"]
    dev = {"id": "d1", "key": "ap:0212379c0fb4", "kind": "ap", "label": "FRITZ!Box", "pos": [120, 80]}
    r = client.put(f"/api/floors/{f1}/devices", json=[dev])
    assert r.status_code == 200 and r.json()["devices"][0]["pos"] == [120.0, 80.0]
    # dasselbe Gerät auf einem zweiten Stockwerk ist nicht erlaubt
    r = client.put(f"/api/floors/{f2}/devices", json=[{**dev, "id": "d2"}])
    assert r.status_code == 409 and "EG" in r.json()["detail"]
    assert client.put(f"/api/floors/{f1}/devices", json=[dev, {**dev, "id": "d3"}]).status_code == 400


def test_deleted_suggestions_stay_deleted(client):
    plan = upload_png(client, hatched_plan())
    fid = client.post("/api/floors", json={"name": "EG", "plan_id": plan["id"],
                                           "crop": {"x": 0, "y": 0, "w": 800, "h": 600}}).json()["id"]
    walls = client.post(f"/api/floors/{fid}/detect", json={}).json()["floor"]["walls"]
    doomed = max(walls, key=lambda w: abs(w["a"][0] - w["b"][0]) + abs(w["a"][1] - w["b"][1]))
    rest = [w for w in walls if w["id"] != doomed["id"]]
    assert client.put(f"/api/floors/{fid}/walls", json=rest).status_code == 200
    again = client.post(f"/api/floors/{fid}/detect", json={"mode": "replace_auto"}).json()["floor"]["walls"]
    assert len(again) == len(rest)                                   # gelöschte Wand kommt nicht zurück
    # Rückgängig (Wand wieder mitschicken) hebt das Merken auf
    assert client.put(f"/api/floors/{fid}/walls", json=again + [doomed]).status_code == 200
    assert client.get(f"/api/floors/{fid}").json()["ignored"] == []
    # „alles neu erkennen“ beginnt von vorn
    fresh = client.post(f"/api/floors/{fid}/detect", json={"mode": "replace_all"}).json()["floor"]
    assert fresh["ignored"] == [] and len(fresh["walls"]) == len(walls)


def test_evaluation(client, tmp_path, monkeypatch):
    import json

    from wifi_survey import catalog
    monkeypatch.setattr(catalog, "HASS_ENV", tmp_path / "fehlt.env")
    catalog._HA_CACHE["at"] = 0
    (tmp_path / "messungen").mkdir()
    m = json.loads(json.dumps(MEASUREMENT))
    # Shelly sieht beide Zugangspunkte; FRITZ!Box schwächer
    m["shellys"][0]["scan"] = [{"bssid": "02:4D:DF:F4:44:7D", "rssi": -58, "ssid": "WLAN", "channel": 6}]
    (tmp_path / "messungen" / "2026-10-30T002046Z.json").write_text(json.dumps(m))
    plan = upload_png(client, hatched_plan())
    fid = client.post("/api/floors", json={"name": "KG", "plan_id": plan["id"], "crop": {"x": 0, "y": 0, "w": 800, "h": 600}}).json()["id"]
    assert client.get(f"/api/floors/{fid}/evaluation").status_code == 409          # ohne Maßstab
    client.put(f"/api/floors/{fid}/scale", json={"a": [0, 0], "b": [800, 0], "length_m": 10})
    walls = [{"id": "w1", "a": [400, 0], "b": [400, 600], "thickness_px": 20}]
    client.put(f"/api/floors/{fid}/walls", json=walls)
    devices = [{"id": "d1", "key": "ap:024ddff4447b", "kind": "ap", "label": "UG-Anschluss", "pos": [200, 300]},
               {"id": "d2", "key": "shelly:021901898fdc", "kind": "shelly", "label": "Waschmaschine 2", "pos": [600, 300]}]
    assert client.put(f"/api/floors/{fid}/devices", json=devices).status_code == 200
    ev = client.get(f"/api/floors/{fid}/evaluation").json()
    dev = ev["devices"][0]
    assert dev["connected"]["rssi"] == -76 and dev["connected"]["rating"] == "schwach"
    assert dev["best"]["rssi"] == -58 and dev["sticky"] is True
    assert any("um 18 dB besser" in f["text"] for f in ev["findings"])
    assert [a["key"] for a in ev["model"]["aps"]] == ["ap:024ddff4447b"] and set(ev["maps"]) == {"ap:024ddff4447b", "best"}
    assert any("fritz.box ist nicht platziert" in f["text"] for f in ev["findings"])
    ov = client.get("/api/evaluation").json()
    assert ov["floors"][0]["name"] == "KG" and "coverage" in ov["floors"][0] and ov["model"]["n"] == 1
    # Simulation: Repeater verschieben, Karte und Vergleich kommen zurück; Empfehlung läuft
    sim = client.post("/api/simulation", json={"floor_id": fid, "moved": {"ap:024ddff4447b": {"floor_id": fid, "pos": [550, 300]}}})
    assert sim.status_code == 200, sim.text
    sim = sim.json()
    assert sim["floor"]["map"].startswith("data:image/png;base64,") and sim["devices"][0]["delta"] > 0
    rec = client.post("/api/simulation/recommend", json={"movable": ["ap:024ddff4447b"], "add": 1})
    assert rec.status_code == 200 and set(rec.json()) >= {"moved", "added", "score", "kept"}
    assert client.post("/api/simulation", json={"added": [{"id": str(i), "floor_id": fid, "pos": [1, 1]} for i in range(6)]}).status_code == 422
    r = client.get(f"/api/floors/{fid}/evaluation/heatmap.png?ap=best")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert client.get(f"/api/floors/{fid}/evaluation/heatmap.png?ap=unbekannt").status_code == 404


def test_outline(client):
    plan = upload_png(client, hatched_plan())
    fid = client.post("/api/floors", json={"name": "EG", "level": 0, "plan_id": plan["id"],
                                           "crop": {"x": 50, "y": 50, "w": 700, "h": 500}}).json()["id"]
    assert client.get(f"/api/floors/{fid}/outline").status_code == 409            # ohne Maßstab
    client.put(f"/api/floors/{fid}/scale", json={"a": [50, 64.5], "b": [650, 64.5], "length_m": 7.30})
    client.post(f"/api/floors/{fid}/detect", json={"mode": "replace_auto"})
    r = client.get(f"/api/floors/{fid}/outline")
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["user"] is None and o["auto"]["polygons"] and o["area_m2"] == o["auto"]["area_m2"] > 0
    poly = [[100, 100], [400, 100], [400, 300], [100, 300]]
    r = client.put(f"/api/floors/{fid}/outline", json={"polygons": [poly]})
    assert r.status_code == 200, r.text
    assert r.json()["user"] == [poly] and 0 < r.json()["area_m2"] < o["area_m2"]
    assert client.get(f"/api/floors/{fid}/outline").json()["area_m2"] == r.json()["area_m2"]
    assert client.put(f"/api/floors/{fid}/outline", json={"polygons": [[[0, 0], [1, 1]]]}).status_code == 422
    # Ausschnitt verschieben: der Umriss wandert mit
    r = client.patch(f"/api/floors/{fid}", json={"crop": {"x": 40, "y": 45, "w": 700, "h": 500}})
    assert r.json()["outline"][0][0] == [110.0, 105.0]
    # zweites, ausgerichtetes Stockwerk sieht den Umriss des ersten
    og = client.post("/api/floors", json={"name": "OG", "level": 1, "plan_id": plan["id"],
                                          "crop": {"x": 50, "y": 50, "w": 700, "h": 500}}).json()["id"]
    client.put(f"/api/floors/{og}/scale", json={"a": [50, 64.5], "b": [650, 64.5], "length_m": 7.30})
    client.patch(f"/api/floors/{og}", json={"reference_floor": fid, "transform": {"dx_m": 0, "dy_m": 0, "rot_deg": 0}})
    o2 = client.get(f"/api/floors/{og}/outline").json()
    assert o2["others"][0]["floor_id"] == fid and o2["others"][0]["user"]
    assert o2["others"][0]["polygons"][0][0] == [110.0, 105.0]
    # zurück zur Automatik
    assert client.put(f"/api/floors/{fid}/outline", json={"polygons": None}).json()["user"] is None


def test_planning_without_measurement(client):
    plan = upload_png(client, hatched_plan())
    fid = client.post("/api/floors", json={"name": "EG", "level": 0, "plan_id": plan["id"],
                                           "crop": {"x": 50, "y": 50, "w": 700, "h": 500}}).json()["id"]
    client.put(f"/api/floors/{fid}/scale", json={"a": [50, 64.5], "b": [650, 64.5], "length_m": 7.30})
    client.post(f"/api/floors/{fid}/detect", json={"mode": "replace_auto"})
    assert client.get("/api/devices/catalog").json() == {"measured_at": None, "devices": []}
    r = client.put(f"/api/floors/{fid}/devices", json=[
        {"id": "d1", "key": "manual:aa11", "kind": "ap", "label": "Router", "pos": [200, 250], "role": "master"},
        {"id": "d2", "key": "manual:bb22", "kind": "ap", "label": "Repeater", "pos": [500, 250], "role": "slave",
         "uplink": "WLAN"}])
    assert r.status_code == 200, r.text
    assert r.json()["devices"][1]["uplink"] == "WLAN"
    ev = client.get(f"/api/floors/{fid}/evaluation")
    assert ev.status_code == 200, ev.text
    body = ev.json()
    assert body["measured_at"] is None and "best" in body["maps"] and body["coverage"]
    assert any("Noch kein Messlauf" in f["text"] for f in body["findings"])
    assert client.get(f"/api/floors/{fid}/evaluation/heatmap.png?ap=best").status_code == 200
    assert "best" in body["maps5"] and body["coverage5"]                       # eigene Zugangspunkte: auch 5 GHz
    assert client.get(f"/api/floors/{fid}/evaluation/heatmap.png?ap=best&band=5").status_code == 200
    assert client.get(f"/api/floors/{fid}/evaluation/heatmap.png?ap=nix&band=5").status_code == 404
    sim = client.post("/api/simulation", json={"floor_id": fid, "moved": {"manual:bb22": {"floor_id": fid, "pos": [600, 300]}}})
    assert sim.status_code == 200 and sim.json()["uplinks"][0]["label"] == "Repeater", sim.text


def test_assign_networks_to_own_access_points(client):
    plan = upload_png(client, hatched_plan())
    fid = client.post("/api/floors", json={"name": "EG", "level": 0, "plan_id": plan["id"],
                                           "crop": {"x": 50, "y": 50, "w": 700, "h": 500}}).json()["id"]
    devs = [{"id": "d1", "key": "manual:aa11", "kind": "ap", "label": "Router", "pos": [200, 250], "role": "master"},
            {"id": "d2", "key": "manual:bb22", "kind": "ap", "label": "Repeater", "pos": [500, 250], "role": "slave"},
            {"id": "d3", "key": "manual:cc33", "kind": "other", "label": "TV", "pos": [300, 250]}]
    client.put(f"/api/floors/{fid}/devices", json=devs)
    r = client.put("/api/devices/manual:aa11/bssids", json={"bssids": ["12:34:56:78:9A:BC", "123456789abd", "02:00:00:00:00:00"]})
    assert r.status_code == 200 and r.json()["bssids"] == ["123456789abc", "123456789abd"], r.text
    # ein Netz gehört zu genau einem Zugangspunkt
    client.put("/api/devices/manual:bb22/bssids", json={"bssids": ["12:34:56:78:9A:BD"]})
    got = {d["key"]: d["bssids"] for d in client.get(f"/api/floors/{fid}").json()["devices"]}
    assert got == {"manual:aa11": ["123456789abc"], "manual:bb22": ["123456789abd"], "manual:cc33": []}
    assert client.put("/api/devices/manual:cc33/bssids", json={"bssids": []}).status_code == 404     # kein Zugangspunkt
    assert client.put("/api/devices/ap:0212379c0fb4/bssids", json={"bssids": []}).status_code == 400
    aps = {a["key"]: a for a in client.get("/api/survey/aps").json()["aps"]}
    assert aps["manual:aa11"]["manual"] and aps["manual:aa11"]["bssids"] == ["123456789abc"]
    # der Editor überschreibt die Zuordnung nicht (er kennt nur seinen alten Stand)
    client.put(f"/api/floors/{fid}/devices", json=devs)
    assert client.get(f"/api/floors/{fid}").json()["devices"][0]["bssids"] == ["123456789abc"]
    # Messpunkt: Werte der zugeordneten Netze zählen für die eigenen Zugangspunkte
    r = client.post(f"/api/floors/{fid}/survey", json={
        "pos": [300, 300], "connection": {"bssid": "12:34:56:78:9a:bc", "rssi": -48, "frequency": 2437},
        "scan": [{"bssid": "12:34:56:78:9A:BD", "rssi": -66, "frequency": 5180, "age_ms": 500},
                 {"bssid": "aa:bb:cc:dd:ee:ff", "rssi": -80, "frequency": 2412, "age_ms": 500}]})
    assert r.status_code == 200, r.text
    pt = r.json()
    assert pt["aps"] == {"manual:aa11": {"2.4": -48}, "manual:bb22": {"5": -66}} and pt["connected"]["ap"] == "manual:aa11"
    assert len(pt["others"]) == 1
    ev = client.get(f"/api/floors/{fid}/evaluation")
    assert ev.status_code == 409   # ohne Wände und Maßstab keine Karte; Eichung prüft test_evaluate


def test_progress_guides_through_the_steps(client):
    def st(sid=None):
        r = client.get("/api/progress")
        assert r.status_code == 200, r.text
        steps = {x["id"]: x for x in r.json()["steps"]}
        return steps[sid] if sid else steps

    assert st("plan")["status"] == "todo" and set(st()) == {"plan", "floors"}
    plan = upload_png(client, hatched_plan())
    assert st("plan")["status"] == "done" and st("floors")["status"] == "todo"
    fid = client.post("/api/floors", json={"name": "EG", "level": 0, "plan_id": plan["id"],
                                           "crop": {"x": 50, "y": 50, "w": 700, "h": 500}}).json()["id"]
    s = st()
    assert s["floors"]["status"] == "done" and s["scale"]["status"] == "todo" and s["scale"]["link"] == f"#/stockwerk/{fid}"
    assert s["walls"]["status"] == "todo" and "align" not in s and s["aps"]["status"] == "todo"
    client.put(f"/api/floors/{fid}/scale", json={"a": [50, 64.5], "b": [650, 64.5], "length_m": 7.30})
    client.post(f"/api/floors/{fid}/detect", json={"mode": "replace_auto"})
    client.put(f"/api/floors/{fid}/devices", json=[
        {"id": "d1", "key": "manual:aa11", "kind": "ap", "label": "Router", "pos": [200, 250], "role": "master"}])
    s = st()
    assert s["scale"]["status"] == "done" and s["aps"]["status"] == "done" and s["walls"]["status"] in ("done", "todo")
    assert s["measure"]["status"] == "optional" and s["evaluate"]["link"] == "#/auswertung"
    # zweites Stockwerk ohne Ausrichtung: Schritt „ausrichten“ offen
    client.post("/api/floors", json={"name": "OG", "level": 1, "plan_id": plan["id"],
                                     "crop": {"x": 50, "y": 50, "w": 700, "h": 500}})
    assert st("align")["status"] == "todo" and st("scale")["status"] == "todo"
