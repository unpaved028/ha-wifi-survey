"""Räume aus den Wänden, Namen und Wahrscheinlichkeit je Raum (Entscheidung 0014)."""

import numpy as np

from wifi_survey import rooms
from wifi_survey.models import Placement, RoomLabel, Wall

from .test_api import client, upload_png  # noqa: F401 (Fixture)
from .test_evaluate import floor
from .test_walls import hatched_plan


def two_rooms(gap_m, devices=(), labels=()):
    """Zwei Räume je 4 × 4 m nebeneinander (1 px = 1 cm), dazwischen eine Wand mit einer Öffnung von gap_m in der Mitte."""
    o, t = 500.0, 24
    ws = [Wall(id="n", a=(o, o), b=(o + 800, o), thickness_px=t), Wall(id="s", a=(o, o + 400), b=(o + 800, o + 400), thickness_px=t),
          Wall(id="w", a=(o, o), b=(o, o + 400), thickness_px=t), Wall(id="e", a=(o + 800, o), b=(o + 800, o + 400), thickness_px=t)]
    half = gap_m * 100 / 2
    ws += [Wall(id="m1", a=(o + 400, o), b=(o + 400, o + 200 - half), thickness_px=12),
           Wall(id="m2", a=(o + 400, o + 200 + half), b=(o + 400, o + 400), thickness_px=12)]
    f = floor("f", 0, walls=ws, devices=devices)
    f.room_labels = list(labels)
    return f


def shelly(mac, x, y):
    return Placement(id=mac, key=f"shelly:{mac}", kind="shelly", label=mac, pos=(x, y))


def test_door_separates_rooms_wide_opening_joins_them():
    res = rooms.compute(two_rooms(0.9))     # innen je 3,76 × 3,76 m abzüglich der halben Mittelwand
    assert [round(r["area_m2"]) for r in res["rooms"]] == [14, 14], res["rooms"]
    assert all(r["contours"] and r["source"] == "auto" for r in res["rooms"])
    assert {r["name"] for r in res["rooms"]} == {"Raum 1", "Raum 2"}
    one = rooms.compute(two_rooms(2.0))
    assert len(one["rooms"]) == 1 and round(one["rooms"][0]["area_m2"]) == 28


def test_names_from_home_assistant_and_own_labels():
    devs = [shelly("aa0000000001", 600, 650), shelly("aa0000000002", 650, 700), shelly("aa0000000003", 700, 750)]
    areas = {"shelly:aa0000000001": "Küche", "shelly:aa0000000002": "Wohnzimmer", "shelly:aa0000000003": "Küche"}
    res = rooms.compute(two_rooms(0.9, devs), areas)
    left = next(r for r in res["rooms"] if r["devices"])
    right = next(r for r in res["rooms"] if not r["devices"])
    assert left["name"] == "Küche / Wohnzimmer" and left["source"] == "ha" and left["ha_areas"] == ["Küche", "Wohnzimmer"]
    assert right["source"] == "auto"
    res = rooms.compute(two_rooms(0.9, devs, [RoomLabel(pos=(1100, 700), name="Bad"), RoomLabel(pos=(620, 600), name="Essen")]),
                        areas)
    names = {r["name"]: r for r in res["rooms"]}
    assert names["Bad"]["source"] == "user" and names["Essen"]["source"] == "user"   # eigener Name vor HA
    assert names["Essen"]["ha_areas"] == ["Küche", "Wohnzimmer"]
    both = rooms.compute(two_rooms(0.9, [shelly("aa0000000001", 600, 650), shelly("aa0000000004", 1100, 650)]),
                         {"shelly:aa0000000001": "Büro", "shelly:aa0000000004": "Büro"})
    assert sorted(r["name"] for r in both["rooms"]) == ["Büro", "Büro 2"]   # gleicher Bereich in zwei Räumen


def test_ranking_and_room_at_position():
    f = two_rooms(0.9)
    res = rooms.compute(f)
    dens = np.where(res["labels"] > 0, 1.0, 0.0)
    dens /= dens.sum()
    rank = rooms.ranking({"f": dens}, {"f": res}, {"f": "EG"})
    assert [r["rank"] for r in rank] == [1, 2] and 98 <= sum(r["share"] for r in rank) <= 102
    assert all(45 <= r["share"] <= 55 for r in rank) and rank[0]["floor"] == "EG"
    left = rooms.room_key_at({"f": res}, f, (600, 700))
    right = rooms.room_key_at({"f": res}, f, (1100, 700))
    assert left and right and left != right and rooms.room_key_at({"f": res}, f, (0, 0)) is None


def test_api_rooms_and_labels(client):  # noqa: F811 (Fixture)
    plan = upload_png(client, hatched_plan())
    fid = client.post("/api/floors", json={"name": "EG", "level": 0, "plan_id": plan["id"],
                                           "crop": {"x": 50, "y": 50, "w": 700, "h": 500}}).json()["id"]
    assert client.get(f"/api/floors/{fid}/rooms").status_code == 409             # ohne Maßstab
    client.put(f"/api/floors/{fid}/scale", json={"a": [50, 64.5], "b": [650, 64.5], "length_m": 7.30})
    client.post(f"/api/floors/{fid}/detect", json={"mode": "replace_auto"})
    r = client.get(f"/api/floors/{fid}/rooms")
    assert r.status_code == 200, r.text
    first = r.json()["rooms"][0]
    assert r.json()["door_m"] == rooms.DOOR_M and first["name"] == "Raum 1" and first["source"] == "auto"
    r = client.put(f"/api/floors/{fid}/room-labels", json={"labels": [{"pos": first["anchor"], "name": "Wohnen"}]})
    assert r.status_code == 200 and r.json()["rooms"][0]["name"] == "Wohnen" and r.json()["rooms"][0]["labels"] == [0]
    assert client.get("/api/project").json()["floors"][0]["room_labels"][0]["name"] == "Wohnen"
    assert client.put(f"/api/floors/{fid}/room-labels", json={"labels": [{"pos": [1, 1], "name": "x" * 41}]}).status_code == 422
    assert client.put(f"/api/floors/{fid}/room-labels", json={"labels": []}).json()["rooms"][0]["name"] == "Raum 1"
