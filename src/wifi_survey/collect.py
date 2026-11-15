"""Messlauf: Mesh-Topologie der FRITZ!Box plus WLAN-Status und -Scans aller Shellys."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from . import shelly
from .config import DATA_DIR as _DATA_DIR
from .fritz import FritzBox

DATA_DIR = _DATA_DIR / "messungen"
SCAN_WORKERS = 4  # parallele Shelly-Scans; klein halten, Scans stören den Funkbetrieb kurz


def _norm_mac(mac: str | None) -> str:
    return (mac or "").upper().replace("-", ":")


def access_points(mesh: dict) -> list[dict]:
    """Mesh-Knoten (Box und Repeater) mit ihren WLAN-Funkzellen und der Anbindung."""
    nodes = {n["uid"]: n for n in mesh["nodes"]}
    aps = []
    for n in mesh["nodes"]:
        if n.get("mesh_role") not in ("master", "slave"):
            continue
        cells, uplink, position = [], None, {}
        for iface in n["node_interfaces"]:
            if iface.get("client_position") and iface.get("name", "").startswith("UPLINK"):
                # Einschätzung von FRITZ!OS zum Platz des Repeaters je Band („ok“, „too_close“ …)
                position["5" if "5G" in iface["name"] else "2.4" if "2G" in iface["name"] else iface["name"]] = \
                    iface["client_position"]
            if iface.get("type") == "WLAN" and iface.get("ssid"):
                cells.append({
                    "name": iface["name"],
                    "bssid": _norm_mac(iface.get("mac_address")),
                    "ssid": iface["ssid"],
                    "channel": iface.get("current_channel"),
                    "band": "5" if "5G" in iface["name"] else "2.4" if "2G" in iface["name"] else iface["name"],
                })
            if n.get("mesh_role") == "slave":
                for link in iface.get("node_links", []):
                    other = nodes.get(link["node_1_uid"] if link["node_2_uid"] == n["uid"] else link["node_2_uid"], {})
                    if other.get("mesh_role") == "master" and link.get("state") == "CONNECTED":
                        uplink = {"type": link["type"], "rate_rx": link.get("cur_data_rate_rx"), "rcpi": link.get("rx_rcpi")}
        aps.append({
            "name": n["device_name"],
            "role": n["mesh_role"],
            "model": n.get("device_model"),
            "mac": _norm_mac(n.get("device_mac_address")),
            "cells": cells,
            "uplink": uplink,
            "uplink_position": position,
        })
    return aps


def wlan_clients(mesh: dict) -> list[dict]:
    """Verbundene WLAN-Clients mit Zugangspunkt, Funkzelle und Signal (Sicht der FRITZ!Box)."""
    nodes = {n["uid"]: n for n in mesh["nodes"]}
    ifaces = {i["uid"]: i for n in mesh["nodes"] for i in n["node_interfaces"]}
    clients, seen = [], set()
    for n in mesh["nodes"]:
        if n.get("mesh_role") not in ("master", "slave"):
            continue
        for iface in n["node_interfaces"]:
            for link in iface.get("node_links", []):
                if link["type"] != "WLAN" or link.get("state") != "CONNECTED" or link["uid"] in seen:
                    continue
                other_uid = link["node_2_uid"] if link["node_1_uid"] == n["uid"] else link["node_1_uid"]
                other = nodes.get(other_uid, {})
                if other.get("mesh_role") in ("master", "slave"):
                    continue
                seen.add(link["uid"])
                ap_iface = ifaces.get(link["node_interface_1_uid"] if link["node_1_uid"] == n["uid"] else link["node_interface_2_uid"], {})
                rcpi = link.get("rx_rcpi")
                clients.append({
                    "name": other.get("device_name"),
                    "mac": _norm_mac(other.get("device_mac_address")),
                    "ap": n["device_name"],
                    "cell": ap_iface.get("name"),
                    "rcpi": None if rcpi in (None, 255) else rcpi,
                    "rate_rx": link.get("cur_data_rate_rx"),
                    "rate_max": link.get("max_data_rate_rx"),
                })
    return clients


def mesh_links(mesh: dict) -> list[dict]:
    """WLAN-Funkstrecken zwischen Zugangspunkten (per WLAN angebundene Repeater), je Richtung ein Eintrag:
    'to' empfängt 'from' mit 'rssi' dBm auf 'band'.

    rx_rcpi misst node_1, tx_rcpi node_2. Beleg: Die RSNI kennt nur die Seite der FRITZ!Box, und sie steht
    bei rx, wenn die FRITZ!Box node_1 ist, sonst bei tx (echte Mesh-Liste, 03.11.2026)."""
    nodes = {n["uid"]: n for n in mesh["nodes"]}
    ifaces = {i["uid"]: i for n in mesh["nodes"] for i in n["node_interfaces"]}
    out, seen = [], set()
    for n in mesh["nodes"]:
        for iface in n["node_interfaces"]:
            for link in iface.get("node_links", []):
                if link.get("type") != "WLAN" or link.get("state") != "CONNECTED" or link["uid"] in seen:
                    continue
                n1, n2 = nodes.get(link["node_1_uid"], {}), nodes.get(link["node_2_uid"], {})
                if n1.get("mesh_role") not in ("master", "slave") or n2.get("mesh_role") not in ("master", "slave"):
                    continue
                seen.add(link["uid"])
                names = " ".join(ifaces.get(link.get(k), {}).get("name", "")
                                 for k in ("node_interface_1_uid", "node_interface_2_uid"))
                band = "5" if "5G" in names else "2.4" if "2G" in names else None
                for frm, to, key in ((n2, n1, "rx_rcpi"), (n1, n2, "tx_rcpi")):
                    v = link.get(key)
                    if band and v not in (None, 255):
                        out.append({"from": _norm_mac(frm.get("device_mac_address")),
                                    "to": _norm_mac(to.get("device_mac_address")), "band": band, "rssi": v})
    return out


def shelly_candidates(hosts: list[dict[str, str]]) -> list[str]:
    """IPs aktiver Hosts, deren Name auf einen Shelly hindeutet."""
    ips = []
    for h in hosts:
        name = (h.get("HostName") or "").lower()
        if h.get("Active") == "1" and h.get("IPAddress") and name.startswith("shelly"):
            ips.append(h["IPAddress"])
    return sorted(set(ips), key=lambda ip: tuple(int(p) for p in ip.split(".")))


def run(scan: bool = True, fritz: FritzBox | None = None) -> dict:
    fritz = fritz or FritzBox.configured()
    mesh = fritz.mesh_list()
    hosts = fritz.host_list()
    candidates = shelly_candidates(hosts)
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        shellys = [s for s in pool.map(lambda ip: shelly.probe(ip, scan=scan), candidates) if s]
    return {
        "version": 1,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "scan": scan,
        "access_points": access_points(mesh),
        "clients": wlan_clients(mesh),
        "mesh_links": mesh_links(mesh),
        "shellys": shellys,
        "shelly_candidates": len(candidates),
    }


def snapshot(fritz: FritzBox | None = None) -> dict:
    """Nur die Mesh-Liste (etwa 5 s): Zugangspunkte und WLAN-Clients mit Signal, ohne Shellys.
    Für die Suche nach einem Gerät, die frische Werte braucht."""
    fritz = fritz or FritzBox.configured()
    mesh = fritz.mesh_list()
    return {"version": 1, "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "access_points": access_points(mesh), "clients": wlan_clients(mesh), "mesh_links": mesh_links(mesh)}


def save(result: dict, directory: Path = DATA_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = result["timestamp"].replace(":", "").replace("+0000", "Z")
    path = directory / f"{stamp}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return path
