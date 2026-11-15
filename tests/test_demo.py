"""Beispielhaus (Paket A17): laden, auswerten, suchen, beenden."""

import json

from wifi_survey import demo

from .test_api import client  # noqa: F401 (Fixture)


def test_demo_house_end_to_end(client, tmp_path):  # noqa: F811 (Fixture)
    r = client.post("/api/demo")
    assert r.status_code == 200, r.text
    p = client.get("/api/project").json()
    assert p["demo"] and len(p["floors"]) == 2 and len(p["plans"]) == 1
    eg, og = sorted(p["floors"], key=lambda f: f["level"])
    assert og["reference_floor"] == eg["id"] and eg["scale"]["px_per_m"] > 0
    assert len(eg["walls"]) == len(demo.WALLS["eg"]) and eg["survey"] and eg["room_labels"]
    assert {d["kind"] for d in eg["devices"]} == {"ap", "client"}
    files = list((tmp_path / "messungen").glob(f"*{demo.MEASUREMENT_SUFFIX}"))
    assert len(files) == 1 and json.loads(files[0].read_text())["demo"]

    ev = client.get(f"/api/floors/{eg['id']}/evaluation")
    assert ev.status_code == 200, ev.text
    assert ev.json()["coverage"]["flaeche_m2"] > 80
    names = {r["name"] for r in client.get(f"/api/floors/{og['id']}/rooms").json()["rooms"]}
    assert {"Kinderzimmer", "Schlafen", "Bad", "Büro"} <= names, names

    devs = client.get("/api/locate/devices").json()
    assert devs["source"] == "beispiel" and devs["error"] is None
    lena = next(d for d in devs["devices"] if d["label"] == "Handy Lena")
    res = client.post("/api/locate", json={"device": lena["key"], "basis": "auto"}).json()
    assert res["best"]["floor"] == "Obergeschoss", res["floors"]
    assert "Kinderzimmer" in [x["name"] for x in res["rooms"][:2]], res["rooms"]

    assert client.post("/api/demo").status_code == 409                   # nur in ein leeres Projekt
    assert client.post("/api/measurements").status_code == 409           # keine echte FRITZ!Box im Beispiel
    assert client.post(f"/api/floors/{eg['id']}/survey", json={"pos": [1, 1], "scan": []}).status_code == 409

    assert client.delete("/api/demo").status_code == 200
    p = client.get("/api/project").json()
    assert not p["demo"] and not p["floors"] and not p["plans"]
    assert not list((tmp_path / "messungen").glob(f"*{demo.MEASUREMENT_SUFFIX}"))
    assert client.delete("/api/demo").status_code == 409


def test_demo_is_reproducible():
    a, b = demo.plan_image(), demo.plan_image()
    assert a.shape == b.shape and (a == b).all() and a.min() == 0 and a.max() == 255
