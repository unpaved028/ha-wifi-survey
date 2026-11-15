"""Shelly-Abfrage über die lokale RPC-Schnittstelle (nur lesend)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

TIMEOUT = 5.0
SCAN_TIMEOUT = 30.0


def _get(ip: str, path: str, timeout: float = TIMEOUT) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://{ip}{path}", timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def probe(ip: str, scan: bool = True) -> dict | None:
    """Liest Geräteinfo, WLAN-Status und optional den WLAN-Scan eines Shelly.

    Gen2+ (RPC): WiFi.GetStatus und WiFi.Scan. Gen1: /status (nur eigener AP, kein Scan).
    Gibt None zurück, wenn unter der IP kein Shelly antwortet.
    """
    info = _get(ip, "/rpc/Shelly.GetDeviceInfo")
    if info and "id" in info:
        result = {
            "ip": ip,
            "id": info["id"],
            "gen": info.get("gen"),
            "model": info.get("model"),
            "app": info.get("app"),
            "fw": info.get("ver"),
            "status": _get(ip, "/rpc/WiFi.GetStatus"),
            "scan": None,
        }
        if scan:
            data = _get(ip, "/rpc/WiFi.Scan", timeout=SCAN_TIMEOUT)
            result["scan"] = data.get("results") if data else None
        return result

    legacy = _get(ip, "/shelly")
    if legacy and legacy.get("type"):
        status = _get(ip, "/status") or {}
        sta = status.get("wifi_sta", {})
        return {
            "ip": ip,
            "id": legacy.get("mac"),
            "gen": 1,
            "model": legacy.get("type"),
            "app": None,
            "fw": legacy.get("fw"),
            "status": {"ssid": sta.get("ssid"), "rssi": sta.get("rssi"), "bssid": None, "channel": None},
            "scan": None,
        }
    return None
