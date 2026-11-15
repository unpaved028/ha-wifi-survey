"""Messen mit dem Handy: Zuordnung der WLAN-Werte, Speichern, Eichung."""

import json

from wifi_survey import survey
from wifi_survey.models import SurveyIn, SurveyPoint

from .test_api import MEASUREMENT, client, upload_png  # noqa: F401 (Fixture)
from .test_walls import hatched_plan

CELLS = survey.ap_cells(MEASUREMENT)


def test_bands_and_channels():
    assert survey.band_of(2437) == "2.4" and survey.channel_of(2437) == 6
    assert survey.band_of(5180) == "5" and survey.channel_of(5180) == 36
    assert survey.band_of(5975) == "6" and survey.channel_of(5975) == 5
    assert survey.band_of(900) is None


def test_make_point_maps_bssids_and_hides_foreign_networks():
    req = SurveyIn(pos=(10, 20), device="Pixel 8",
                   connection={"bssid": "02:12:37:9c:0f:b7", "ssid": "WLAN", "rssi": -48, "frequency": 2462, "link_mbps": 144},
                   scan=[{"bssid": "02:12:37:9C:0F:B7", "ssid": "WLAN", "rssi": -51, "frequency": 2462, "age_ms": 900},
                         {"bssid": "02:12:37:9C:0F:B9", "ssid": "Gast", "rssi": -60, "frequency": 5500, "age_ms": 900},
                         {"bssid": "02:4D:DF:F4:44:7D", "ssid": "WLAN", "rssi": -71, "frequency": 2437, "age_ms": 1200},
                         {"bssid": "02:4D:DF:F4:44:7D", "ssid": "WLAN", "rssi": -40, "frequency": 2437, "age_ms": 120000},
                         {"bssid": "11:22:33:44:55:66", "ssid": "Nachbar", "rssi": -80, "frequency": 2412, "age_ms": 800},
                         {"bssid": "11:22:33:44:55:77", "ssid": "Nachbar2", "rssi": -75, "frequency": 2412, "age_ms": 800}])
    p = survey.make_point("s1", req, CELLS)
    box, ug = "ap:0212379c0fb4", "ap:024ddff4447b"
    assert p.aps[box] == {"2.4": -48, "5": -60}          # Verbindung schlägt Scan; Gastnetz über das Präfix
    assert p.aps[ug] == {"2.4": -71}                     # der alte Scan-Wert (2 Minuten) zählt nicht
    assert p.connected == {"ap": box, "band": "2.4", "rssi": -48, "link_mbps": 144}
    assert p.others == [{"band": "2.4", "channel": 1, "count": 2, "rssi": -75}]
    assert "Nachbar" not in p.model_dump_json() and "11:22" not in p.model_dump_json()
    # verborgene BSSID (ohne Berechtigung): Verbindung ohne Zugangspunkt
    hidden = survey.make_point("s2", SurveyIn(pos=(0, 0), connection={"bssid": "02:00:00:00:00:00", "rssi": -50, "frequency": 2462}), CELLS)
    assert hidden.connected["ap"] is None and hidden.aps == {}


def test_make_point_ignores_placeholder_signals():
    # Android meldet im Scan mitunter 0 dBm (gesehen 03.11.2026 beim Pixel 9); als „stärkster Wert“ hätte er
    # den echten Wert desselben Zugangspunkts verdrängt und das Modell verzerrt.
    req = SurveyIn(pos=(0, 0), connection={"bssid": "02:4d:df:f4:44:7d", "rssi": 0, "frequency": 2437},
                   scan=[{"bssid": "02:12:37:9C:0F:B7", "rssi": -81, "frequency": 2462, "age_ms": 100},
                         {"bssid": "02:12:37:9C:0F:B7", "rssi": 0, "frequency": 2462, "age_ms": 100},
                         {"bssid": "02:12:37:9C:0F:B9", "rssi": -127, "frequency": 5500, "age_ms": 100}])
    p = survey.make_point("s3", req, CELLS)
    assert p.aps == {"ap:0212379c0fb4": {"2.4": -81}} and p.connected is None
    assert survey.valid_rssi(-10) and survey.valid_rssi(-110) and not survey.valid_rssi(-5) and not survey.valid_rssi(None)


def test_stored_point_drops_placeholders():
    """Ältere Rundgänge enthalten noch 0 dBm (Platzhalter von Android); beim Laden fallen sie weg."""
    p = SurveyPoint.model_validate({"id": "s1", "pos": (0, 0), "aps": {"ap:a": {"2.4": 0, "5": -60}, "ap:b": {"2.4": -127}}})
    assert p.aps == {"ap:a": {"5": -60}}


def test_survey_api_and_calibration(client, tmp_path, monkeypatch):  # noqa: F811 (Fixture)
    from wifi_survey import catalog
    monkeypatch.setattr(catalog, "HASS_ENV", tmp_path / "fehlt.env")
    catalog._HA_CACHE["at"] = 0
    (tmp_path / "messungen").mkdir()
    (tmp_path / "messungen" / "2026-10-30T002046Z.json").write_text(json.dumps(MEASUREMENT))
    plan = upload_png(client, hatched_plan())
    fid = client.post("/api/floors", json={"name": "EG", "plan_id": plan["id"], "crop": {"x": 0, "y": 0, "w": 800, "h": 600}}).json()["id"]
    client.put(f"/api/floors/{fid}/scale", json={"a": [0, 0], "b": [800, 0], "length_m": 10})
    client.put(f"/api/floors/{fid}/devices", json=[{"id": "a", "key": "ap:024ddff4447b", "kind": "ap", "label": "UG", "pos": [100, 300]}])
    aps = client.get("/api/survey/aps").json()["aps"]
    assert {"key": "ap:024ddff4447b", "label": "UG", "floor": "EG", "manual": False,
            "bssids": ["024ddff4447b", "024ddff4447d"]} in aps
    body = {"pos": [500, 300], "connection": {"bssid": "02:4d:df:f4:44:7d", "rssi": -62, "frequency": 2437, "link_mbps": 72},
            "scan": [{"bssid": "02:12:37:9c:0f:b7", "rssi": -75, "frequency": 2462, "age_ms": 500}]}
    r = client.post(f"/api/floors/{fid}/survey", json=body)
    assert r.status_code == 200, r.text
    pt = r.json()
    assert pt["aps"] == {"ap:024ddff4447b": {"2.4": -62}, "ap:0212379c0fb4": {"2.4": -75}}
    assert client.post(f"/api/floors/{fid}/survey", json={"pos": [1, 1]}).status_code == 422
    ev = client.get(f"/api/floors/{fid}/evaluation").json()
    assert ev["model"]["n_survey"] == 1 and ev["survey"][0]["best"]["rssi"] == -62
    assert any(s["label"] == "Messpunkt 1" and s["measured"] == -62 for s in ev["model"]["samples"])
    # Ausschnitt ändern: Messpunkt und Geräte wandern mit
    client.patch(f"/api/floors/{fid}", json={"crop": {"x": 100, "y": 0, "w": 700, "h": 600}})
    f = client.get(f"/api/floors/{fid}").json()
    assert f["survey"][0]["pos"] == [400.0, 300.0] and f["devices"][0]["pos"] == [0.0, 300.0]
    assert client.delete(f"/api/floors/{fid}/survey/{pt['id']}").status_code == 200
    assert client.get(f"/api/floors/{fid}").json()["survey"] == []
    assert client.delete(f"/api/floors/{fid}/survey/{pt['id']}").status_code == 404
    assert client.get("/app/wifi-survey.apk").status_code == 404
