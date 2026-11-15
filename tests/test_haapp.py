"""Betrieb als Home-Assistant-App: Projekt übertragen (Export/Import), Einstellungen aus der App,
Zugang zu HA über den Supervisor."""

import io
import json
import zipfile

import pytest

from wifi_survey import catalog, config, fritz, haapp

from .test_api import MEASUREMENT, client, upload_png  # noqa: F401 (Fixture)
from .test_walls import hatched_plan


def _project_with_floor(client):  # noqa: F811
    plan = upload_png(client, hatched_plan())
    r = client.post("/api/floors", json={"name": "Erdgeschoss", "level": 0, "plan_id": plan["id"], "page": 0,
                                         "crop": {"x": 50, "y": 50, "w": 700, "h": 500}})
    assert r.status_code == 200, r.text
    return r.json()


def test_export_import_roundtrip(client, tmp_path):  # noqa: F811
    floor = _project_with_floor(client)
    meas = tmp_path / "messungen"
    meas.mkdir()
    (meas / "2026-10-30T002046Z.json").write_text(json.dumps(MEASUREMENT))

    r = client.get("/api/project/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    data = r.content
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("wifi-survey-export.json"))
    assert manifest["format"] == "wifi-survey-export" and manifest["floors"] == 1
    assert {"projekt/projekt.json", f"projekt/stockwerke/{floor['id']}.png", "messungen/2026-10-30T002046Z.json"} <= names
    assert not any(n.endswith(".bak") for n in names)

    # Projekt verändern, dann den Export wieder einspielen
    assert client.delete(f"/api/floors/{floor['id']}").status_code in (200, 204)
    assert client.get("/api/project").json()["floors"] == []
    (meas / "2026-10-30T002046Z.json").unlink()
    r = client.post("/api/project/import", files={"file": ("export.zip", data, "application/zip")})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["floors"] == 1 and res["measurements_added"] == 1
    assert res["backup"].startswith("sicherungen/projekt-")
    assert (tmp_path / res["backup"] / "projekt.json").exists()        # altes Projekt aufbewahrt
    project = client.get("/api/project").json()
    assert [f["id"] for f in project["floors"]] == [floor["id"]]
    assert client.get(f"/api/floors/{floor['id']}/image.png").status_code == 200
    assert (meas / "2026-10-30T002046Z.json").exists()


def _zip(entries: dict[str, bytes | str], manifest: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if manifest is not False:
            zf.writestr("wifi-survey-export.json", json.dumps(manifest or {"format": "wifi-survey-export", "version": 1}))
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


@pytest.mark.parametrize("entries, manifest, text", [
    ({"projekt/projekt.json": "{}"}, False, "keine Exportdatei"),
    ({"projekt/projekt.json": "{}"}, {"format": "anderes"}, "keine Exportdatei"),
    ({"projekt/projekt.json": "{}"}, {"format": "wifi-survey-export", "version": 99}, "neueren Version"),
    ({"projekt/projekt.json": "{}", "../boese.txt": "x"}, None, "unerwarteter Eintrag"),
    ({"projekt/projekt.json": "{}", "/etc/boese": "x"}, None, "unerwarteter Eintrag"),
    ({"projekt/projekt.json": "{}", "anderes/datei": "x"}, None, "unerwarteter Eintrag"),
    ({"messungen/a.json": "{}"}, None, "projekt.json fehlt"),
])
def test_import_rejects_bad_files(client, tmp_path, entries, manifest, text):  # noqa: F811
    _project_with_floor(client)
    r = client.post("/api/project/import", files={"file": ("x.zip", _zip(entries, manifest), "application/zip")})
    assert r.status_code == 400 and text in r.json()["detail"], r.text
    assert len(client.get("/api/project").json()["floors"]) == 1      # Projekt unverändert
    assert not (tmp_path / "boese.txt").exists()
    assert not list(tmp_path.glob(".import-*"))                       # nichts liegen geblieben


def test_import_rejects_non_zip(client):  # noqa: F811
    r = client.post("/api/project/import", files={"file": ("x.zip", b"kein zip", "application/zip")})
    assert r.status_code == 400


def test_info_outside_ha(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    info = client.get("/api/info").json()
    assert info["ha_app"] is False and info["direct_url"] is None and info["ingress"] is False
    assert client.get("/api/info", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"}).json()["ingress"] is True


def test_fritz_access_from_app_options(tmp_path, monkeypatch):
    opts = tmp_path / "options.json"
    monkeypatch.setattr(config, "OPTIONS_FILE", opts)
    monkeypatch.setattr(fritz, "ENV_FILE", tmp_path / "fehlt.env")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")
    with pytest.raises(RuntimeError, match="Konfiguration der App"):
        fritz.FritzBox.configured()
    opts.write_text(json.dumps({"fritzbox_host": "192.168.178.1", "fritzbox_user": "u", "fritzbox_password": "p"}))
    box = fritz.FritzBox.configured()
    # Passwort nur vergleichen, nie ausgeben (falls doch echte Zugangsdaten gelesen würden)
    assert (box.host, box.user, box.password == "p") == ("192.168.178.1", "u", True)

    # eigenständig: Datei wie bisher
    monkeypatch.delenv("SUPERVISOR_TOKEN")
    opts.unlink()
    env = tmp_path / "fritz.env"
    env.write_text("FRITZ_HOST=fritz.box\nFRITZ_USERNAME=a\nFRITZ_PASSWORD='b'\n")
    monkeypatch.setattr(fritz, "ENV_FILE", env)
    box = fritz.FritzBox.configured()
    assert (box.host, box.user == "a", box.password == "b") == ("fritz.box", True, True)


def test_ha_access_prefers_supervisor(tmp_path, monkeypatch):
    env = tmp_path / "hass.env"
    env.write_text("HASS_URL=http://ha:8123/\nHASS_TOKEN=t\n")
    monkeypatch.setattr(catalog, "HASS_ENV", env)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert catalog.ha_access() == ("http://ha:8123", "t")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "s")
    assert catalog.ha_access() == ("http://supervisor/core", "s")
    monkeypatch.delenv("SUPERVISOR_TOKEN")
    monkeypatch.setattr(catalog, "HASS_ENV", tmp_path / "fehlt.env")
    assert catalog.ha_access() is None


def test_host_ip_prefers_primary():
    net = {"interfaces": [
        {"interface": "wlan0", "primary": False, "ipv4": {"address": ["10.0.0.5/24"]}},
        {"interface": "end0", "primary": True, "ipv4": {"address": ["192.168.178.180/24"]}},
        {"interface": "docker0", "primary": False, "ipv4": {"address": []}},
    ]}
    assert haapp.host_ip(net) == "192.168.178.180"
    assert haapp.host_ip({"interfaces": [net["interfaces"][0]]}) == "10.0.0.5"
    assert haapp.host_ip({}) is None
