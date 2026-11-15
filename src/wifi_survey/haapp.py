"""Betrieb als App unter Home Assistant: Angaben vom Supervisor (nur lesend).

Die Oberfläche läuft über Ingress (Seitenleiste von HA, mit HA-Anmeldung). Die Android-App zum
Messen braucht dagegen eine direkte Adresse im Heimnetz: Die gibt es nur, wenn der Port der App in
ihrer Netzwerk-Konfiguration freigegeben ist.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

SUPERVISOR = "http://supervisor"
APP_PORT = "8099/tcp"        # Port im Container (Ingress und Direktzugriff), siehe ha-app/wifi_survey/config.yaml
_TTL = 60                    # Sekunden
_cache: dict = {"at": 0.0, "url": None}


def _get(path: str) -> dict:
    req = urllib.request.Request(SUPERVISOR + path, headers={"Authorization": f"Bearer {os.environ['SUPERVISOR_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode()).get("data") or {}


def host_ip(network: dict) -> str | None:
    """IPv4-Adresse des HA-Rechners im Heimnetz (bevorzugt die primäre Schnittstelle)."""
    best = None
    for iface in network.get("interfaces", []):
        addrs = (iface.get("ipv4") or {}).get("address") or []
        if not addrs:
            continue
        ip = addrs[0].split("/")[0]
        if iface.get("primary"):
            return ip
        best = best or ip
    return best


def direct_url() -> str | None:
    """http://<HA-Rechner>:<Port>, wenn der Port der App freigegeben ist, sonst None."""
    if not os.environ.get("SUPERVISOR_TOKEN"):
        return None
    if time.time() - _cache["at"] < _TTL:
        return _cache["url"]
    url = None
    try:
        port = (_get("/addons/self/info").get("network") or {}).get(APP_PORT)
        ip = host_ip(_get("/network/info")) if port else None
        if port and ip:
            url = f"http://{ip}:{port}"
    except (OSError, ValueError, KeyError):
        url = None
    _cache.update(at=time.time(), url=url)
    return url
