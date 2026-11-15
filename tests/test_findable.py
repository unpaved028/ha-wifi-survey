"""Hintergrundmodus „findbar“ (Entscheidung 0010): Meldung des ruhenden Handys, Suche mit dem eigenen Scan,
Scan am Fundort als Messpunkt."""

from datetime import UTC, datetime, timedelta

import pytest

from wifi_survey import api as api_mod
from wifi_survey import evaluate as ev
from wifi_survey import findable, fritz, locate

from .test_locate import AP1, AP2, PHONE, client_store, house, rssi_at  # noqa: F401 (Fixture)

PHONE_MAC = "AA:BB:CC:00:11:22"   # wie der Client „Handy“ im Messlauf von house()


def phone_scan(pos=PHONE, level=0, att=0, age_ms=7 * 60 * 1000):
    """Scan des Handys: beide Zugangspunkte (2,4 GHz), ein fremdes Netz, ein Platzhalter mit 0 dBm. Im Hintergrund
    nimmt die App vorhandene Ergebnisse aus der Ruhephase: oft einige Minuten alt."""
    return [{"bssid": "02:12:37:9C:0F:B7", "ssid": "", "rssi": rssi_at(AP1, pos, level) - att, "frequency": 2462, "age_ms": age_ms},
            {"bssid": "02:4D:DF:F4:44:7D", "ssid": "", "rssi": rssi_at(AP2, pos, level) - att, "frequency": 2437, "age_ms": age_ms},
            {"bssid": "02:4D:DF:F4:44:7D", "ssid": "", "rssi": 0, "frequency": 2437, "age_ms": age_ms},
            {"bssid": "11:22:33:44:55:66", "ssid": "Nachbar", "rssi": -70, "frequency": 2412, "age_ms": age_ms}]


def report_body(**kw):
    return {"device": "Pixel 9", "app_version": "0.2.0", "still_s": 1200,
            "connection": {"bssid": "02:12:37:9c:0f:b7", "rssi": rssi_at(AP1, PHONE, 0), "frequency": 2462}, "scan": phone_scan(), **kw}


@pytest.fixture
def hosts(monkeypatch):
    """FRITZ!Box-Host-Liste: IP-Adresse -> MAC und Name (TestClient meldet sich als „testclient“)."""
    table = {"testclient": {"mac": PHONE_MAC, "name": "Pixel-9"}}

    class Box:
        def host_by_ip(self, ip):
            return table.get(ip)
    monkeypatch.setattr(fritz.FritzBox, "configured", classmethod(lambda cls: Box()))
    return table


def test_locate_scan_finds_floor_and_tolerates_covered_phone():
    p, m = house()
    base = ev.evaluate_building(p, m)
    evals = {f.id: ev.evaluate_floor(p, f, m, base) for f in p.floors}
    reading = {"ap": AP1, "band": "2.4", "rssi": rssi_at(AP1, PHONE, 0)}
    single = locate.locate(base, evals, p.floors, reading)
    q1 = locate.assess(single, base["building"], p.floors, p.floors[0], PHONE)
    for att in (0, 12):     # 12 dB: Handy unter einer Decke, alle Werte gleich schwächer
        rep = {"t": "2026-11-03T10:00:00+00:00",
               "aps": {AP1: {"2.4": rssi_at(AP1, PHONE, 0) - att}, AP2: {"2.4": rssi_at(AP2, PHONE, 0) - att}}}
        res = locate.locate_scan(base, evals, p.floors, rep, reading)
        q = locate.assess(res, base["building"], p.floors, p.floors[0], PHONE)
        assert res["best"]["floor_id"] == "eg" and res["scan"] == {"t": rep["t"], "n": 2}, att
        assert q["in_region"], (att, q)          # zugedeckt: alle Werte schwächer, der Ort bleibt im Bereich
        if att == 0:
            assert q["error_m"] < 3 and q["error_m"] <= q1["error_m"], (q, q1)   # zwei Zugangspunkte statt einem
    with pytest.raises(ValueError):
        locate.locate_scan(base, evals, p.floors, {"t": "x", "aps": {"ap:ffffffffffff": {"2.4": -60}}}, reading)


def test_usable_needs_same_ap_and_recent_report():
    now = datetime.now(UTC)
    rep = {"t": now.isoformat(), "n": 3, "connected": {"ap": AP1, "band": "5", "rssi": -55},
           "aps": {AP1: {"5": -55, "2.4": -50}, AP2: {"2.4": -75}}}
    assert findable.usable(rep, {"ap": AP1, "band": "2.4"}) == (True, "")   # Bandwechsel am selben Zugangspunkt: ruht noch
    ok, why = findable.usable(rep, {"ap": AP2, "band": "2.4"})
    assert not ok and "anderen Zugangspunkt" in why
    assert findable.usable(rep, None)[0]                                   # ohne aktuelle Werte der FRITZ!Box
    old = {**rep, "t": (now - timedelta(hours=findable.MAX_AGE_H + 1)).isoformat()}
    assert not findable.usable(old, {"ap": AP1})[0]
    assert findable.usable(None, {"ap": AP1}) == (False, "")
    ok, why = findable.usable({**rep, "n": 2, "aps": {AP1: {"5": -55, "2.4": -50}}}, {"ap": AP1})
    assert not ok and "nur den verbundenen Zugangspunkt" in why    # beide Bänder, aber nur ein Zugangspunkt
    assert findable.mac_of("client:aabbcc001122") == "aabbcc001122" and findable.mac_of("shelly:aabbcc001122") is None


def test_api_report_search_found_and_delete(client_store, hosts, monkeypatch):  # noqa: F811 (Fixture)
    client, store, m = client_store
    r = client.post("/api/findable/report", json=report_body())
    assert r.status_code == 200, r.text
    assert r.json()["device"] == "client:aabbcc001122" and r.json()["name"] == "Pixel-9" and r.json()["n"] == 2
    rep = findable.load(store.root.parent, "aabbcc001122")
    assert set(rep["aps"]) == {AP1, AP2} and rep["aps"][AP2] == {"2.4": rssi_at(AP2, PHONE, 0)}   # 0 dBm verworfen
    assert "Nachbar" not in str(rep) and "112233" not in str(rep) and "others" not in rep
    # Scan-Ergebnisse älter als die Ruhephase (über 35 min) zählen nicht, dann bleibt nur die Verbindung
    old = client.post("/api/findable/report", json=report_body(scan=phone_scan(age_ms=40 * 60 * 1000))).json()
    assert old["n"] == 1
    assert client.post("/api/findable/report", json=report_body()).json()["n"] == 2
    assert client.get("/api/findable").json()["reports"][0]["device"] == "client:aabbcc001122"
    dev = next(d for d in client.get("/api/locate/devices").json()["devices"] if d["key"] == "client:aabbcc001122")
    assert dev["findable"]["n"] == 2 and dev["findable"]["still_s"] == 1200 and dev["findable"]["model"] == "Pixel 9"

    res = client.post("/api/locate", json={"device": "client:aabbcc001122"}).json()
    assert res["basis"] == "scan" and res["scan"]["n"] == 2 and res["findable"]["usable"] and res["best"]["floor_id"] == "eg"
    assert res["reading"]["ap"] == AP1                                     # Wert der FRITZ!Box bleibt für den Fundort
    alt = client.post("/api/locate", json={"device": "client:aabbcc001122", "basis": "fritzbox"}).json()
    assert alt["basis"] == "fritzbox" and alt["scan"] is None and alt["findable"]["usable"]

    # Fundort mit dem Scan: zusätzlich ein vollständiger Messpunkt, der mit dem Fundort gelöscht wird
    body = {"device": "client:aabbcc001122", "label": "Pixel-9", "pos": list(PHONE), "reading": res["reading"],
            "scan_t": res["scan"]["t"]}
    fp = client.post("/api/floors/eg/found", json=body).json()
    assert fp["survey_point"] is True and fp["in_region"] is True
    sp = store.load().floor("eg").survey
    assert len(sp) == 1 and sp[0].found == fp["id"] and sp[0].aps[AP2] == {"2.4": rssi_at(AP2, PHONE, 0)}
    labels = [s["label"] for s in client.get("/api/floors/eg/evaluation").json()["model"]["samples"]]
    assert "Messpunkt 1 (Scan am Fundort)" in labels
    assert client.delete(f"/api/floors/eg/found/{fp['id']}").status_code == 200
    assert store.load().floor("eg").survey == []
    fp2 = client.post("/api/floors/eg/found", json={**body, "scan_t": "2026-01-01T00:00:00+00:00"}).json()
    assert fp2["survey_point"] is False                                    # anderer Scan als bei der Suche

    # Handy an einem anderen Zugangspunkt als bei der Meldung: bewegt, Suche mit dem Wert der FRITZ!Box
    from wifi_survey import collect
    snap = {"timestamp": "2026-11-03T10:00:00+00:00", "access_points": m["access_points"],
            "clients": [{**m["clients"][0], "ap": "OG-Repeater", "rcpi": -60}]}
    monkeypatch.setattr(collect, "snapshot", lambda: snap)
    client.get("/api/locate/devices?refresh=true")
    moved = client.post("/api/locate", json={"device": "client:aabbcc001122"}).json()
    assert moved["basis"] == "fritzbox" and not moved["findable"]["usable"] and "anderen Zugangspunkt" in moved["findable"]["why"]

    assert client.delete("/api/findable/report").json() == {"deleted": True}
    assert client.get("/api/findable").json()["reports"] == []
    hosts.clear()                                                          # IP unbekannt (nach Ablauf des Zwischenspeichers)
    t_now = api_mod.time.time()
    monkeypatch.setattr(api_mod.time, "time", lambda: t_now + 700)
    r = client.post("/api/findable/report", json=report_body())
    assert r.status_code == 409 and "kennt kein Gerät" in r.json()["detail"]


def test_soap_sends_arguments(monkeypatch):
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return (b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                    b'<u:X_AVM-DE_GetSpecificHostEntryByIPResponse xmlns:u="urn:dslforum-org:service:Hosts:1">'
                    b'<NewMACAddress>AA:BB:CC:00:11:22</NewMACAddress><NewHostName>Pixel-9</NewHostName>'
                    b'</u:X_AVM-DE_GetSpecificHostEntryByIPResponse></s:Body></s:Envelope>')

    class Opener:
        def open(self, req, timeout=None):
            sent["body"] = req.data.decode()
            return Resp()
    box = fritz.FritzBox("fritz.box", "u", "p")
    monkeypatch.setattr(box, "_opener", lambda: Opener())
    assert box.host_by_ip("192.168.178.176") == {"mac": "AA:BB:CC:00:11:22", "name": "Pixel-9"}
    assert "<NewIPAddress>192.168.178.176</NewIPAddress>" in sent["body"]


def test_usable_detects_moved_phone_by_fritzbox_value():
    """Bei der Meldung empfing die FRITZ!Box das Handy mit −50 dBm; jetzt deutlich anders: bewegt (Entscheidung 0014)."""
    rep = {"t": datetime.now(UTC).isoformat(), "n": 4, "aps": {AP1: {"2.4": -50}, AP2: {"2.4": -70}},
           "connected": {"ap": AP1, "band": "2.4", "rssi": -50}, "fritz": {"ap": AP1, "band": "2.4", "rssi": -50}}
    assert findable.usable(rep, {"ap": AP1, "band": "2.4", "rssi": -57}) == (True, "")
    ok, why = findable.usable(rep, {"ap": AP1, "band": "2.4", "rssi": -66})
    assert not ok and "16 dB" in why and "bewegt" in why
    assert findable.usable(rep, {"ap": AP1, "band": "5", "rssi": -70})[0]   # anderes Band: nicht vergleichbar
