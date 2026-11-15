"""Gerätekatalog zum Platzieren: Zugangspunkte, Shellys und WLAN-Clients aus dem letzten
Messlauf, Namen und Räume (Bereiche) aus Home Assistant, sofern erreichbar."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

HASS_ENV = Path(os.environ.get("WIFI_SURVEY_HASS_ENV", Path.home() / ".config" / "hass.env"))
SUPERVISOR_CORE = "http://supervisor/core"   # HA-API für Apps, Token in SUPERVISOR_TOKEN
_HA_CACHE: dict = {"at": 0.0, "data": {}}
_HA_TTL = 300  # Sekunden

# Name|Bereich|Verbindungen je Gerät der Integrationen shelly und mqtt (Zigbee2MQTT)
_TEMPLATE = (
    "{%- for d in (integration_entities('shelly') + integration_entities('mqtt'))"
    " | map('device_id') | reject('none') | unique -%}"
    "{{ device_attr(d, 'name_by_user') or device_attr(d, 'name') }}|{{ area_name(d) or '' }}"
    "|{{ device_attr(d, 'connections') }} {{ device_attr(d, 'identifiers') }}\n"
    "{% endfor -%}"
)


def norm_mac(mac: str | None) -> str:
    return re.sub(r"[^0-9a-f]", "", (mac or "").lower())


def latest_measurement(directory: Path) -> dict | None:
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    for f in reversed(files):
        try:
            return json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _read_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    return env


def ha_access() -> tuple[str, str] | None:
    """Adresse und Token der HA-API: als HA-App über den Supervisor, sonst aus HASS_ENV."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:
        return SUPERVISOR_CORE, token
    try:
        env = _read_env(HASS_ENV)
        return env["HASS_URL"].rstrip("/"), env["HASS_TOKEN"]
    except (OSError, KeyError):
        return None


def ha_names() -> dict[str, dict[str, str]]:
    """MAC (ohne Trenner) -> {"name", "area"} für Shelly-Geräte in Home Assistant.

    Zigbee-Geräte werden über ihre IEEE-Adresse zugeordnet (Shelly: MAC mit „fffe“ in der Mitte).
    Ist HA nicht erreichbar, kommt ein leeres Ergebnis zurück.
    """
    if time.time() - _HA_CACHE["at"] < _HA_TTL:
        return _HA_CACHE["data"]
    data: dict[str, dict[str, str]] = {}
    access = ha_access()
    try:
        if access is None:
            raise OSError("kein Zugang zu Home Assistant")
        base, token = access
        req = urllib.request.Request(
            base + "/api/template",
            data=json.dumps({"template": _TEMPLATE}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode()
        for line in text.splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            name, area, conns = parts
            macs = [norm_mac(m) for m in re.findall(r"'mac',\s*'([0-9a-fA-F:]+)'", conns)]
            for ieee in re.findall(r"0x([0-9a-fA-F]{16})", conns):
                ieee = ieee.lower()
                if ieee[6:10] == "fffe":
                    macs.append(ieee[:6] + ieee[10:])
            for mac in macs:
                # WLAN-Gerät hat Vorrang vor dem Zigbee-Gegenstück, Bereich wird ergänzt
                entry = data.setdefault(mac, {"name": name, "area": area})
                entry["area"] = entry["area"] or area
    except (OSError, KeyError, ValueError):
        data = {}
    _HA_CACHE.update(at=time.time(), data=data)
    return data


def build_catalog(measurement: dict, names: dict[str, dict[str, str]]) -> list[dict]:
    cell_ap = {norm_mac(c["bssid"]): ap["name"] for ap in measurement.get("access_points", []) for c in ap.get("cells", [])}
    out: list[dict] = []
    ap_macs = set()
    for ap in measurement.get("access_points", []):
        mac = norm_mac(ap.get("mac"))
        ap_macs.add(mac)
        label = ap["name"] if ap.get("role") != "master" else f"{ap.get('model') or 'FRITZ!Box'} ({ap['name']})"
        out.append({"key": f"ap:{mac}", "kind": "ap", "label": label, "area": "", "model": ap.get("model") or "",
                    "detail": "Mesh-Master" if ap.get("role") == "master" else f"Repeater, Anbindung {(ap.get('uplink') or {}).get('type', '?')}"})
    shelly_macs = set()
    for s in measurement.get("shellys", []):
        mac = norm_mac(re.search(r"([0-9A-Fa-f]{12})$", s.get("id") or "").group(1) if re.search(r"([0-9A-Fa-f]{12})$", s.get("id") or "") else "")
        if not mac:
            continue
        shelly_macs.add(mac)
        st = s.get("status") or {}
        ha = names.get(mac, {})
        ap = cell_ap.get(norm_mac(st.get("bssid")), "")
        rssi = st.get("rssi")
        detail = ", ".join(x for x in [s.get("model") or "", f"{rssi} dBm an {ap}" if rssi is not None and ap else "", s.get("ip") or ""] if x)
        out.append({"key": f"shelly:{mac}", "kind": "shelly", "label": ha.get("name") or s.get("id"), "area": ha.get("area", ""),
                    "model": s.get("model") or "", "detail": detail})
    for c in measurement.get("clients", []):
        mac = norm_mac(c.get("mac"))
        if not mac or mac in shelly_macs or mac in ap_macs:
            continue
        detail = f"{c['rcpi']} dBm an {c['ap']}" if c.get("rcpi") is not None else f"an {c.get('ap')}"
        out.append({"key": f"client:{mac}", "kind": "client", "label": c.get("name") or mac, "area": "", "model": "", "detail": detail})
    order = {"ap": 0, "shelly": 1, "client": 2}
    return sorted(out, key=lambda d: (order[d["kind"]], d["area"] == "", d["area"].lower(), d["label"].lower()))
