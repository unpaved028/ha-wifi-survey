"""Hintergrundmodus „findbar“ (Entscheidung 0010).

Die Android-App meldet einen WLAN-Scan, wenn das Handy ruht: bei zwei Prüfungen im Abstand von mindestens
10 Minuten am selben Zugangspunkt mit fast gleichem Signal und mit ausgeschaltetem Bildschirm. Mit dem Scan
sieht die Suche alle Zugangspunkte statt nur des einen, an dem das Handy hängt.

- Je Gerät bleibt nur die letzte Meldung, ohne Verlauf, und nur mit Werten der eigenen Zugangspunkte
  (fremde Netze werden verworfen).
- Zugeordnet wird über die IP-Adresse der Meldung: Die FRITZ!Box kennt zu jeder IP die WLAN-MAC, unter der das
  Gerät auch in der Mesh-Liste steht. Die (oft zufällige) MAC sieht die App selbst nicht.
- Die Suche nutzt eine Meldung nur, solange sie zur FRITZ!Box passt: gleicher Zugangspunkt, höchstens MAX_AGE_H alt.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from . import survey as survey_io
from .catalog import norm_mac
from .models import FindableIn, SurveyIn

MAX_AGE_H = 48
# Die App schickt nur Scan-Ergebnisse aus der Ruhephase, höchstens 30 Minuten alt (beim Rundgang gilt 1 Minute,
# weil man dort geht). Bis 03.11.2026 galt auch hier 1 Minute: Dann blieb oft nur der verbundene Zugangspunkt übrig.
SCAN_MAX_AGE_S = 35 * 60
MIN_APS = 2      # mit nur einem Zugangspunkt bringt der Scan nichts gegenüber dem Wert der FRITZ!Box
# Wert der FRITZ!Box bei der Meldung und bei der Suche: Weicht er um mehr ab, wurde das Handy wohl bewegt
# (Entscheidung 0014). Ruhende Handys schwanken an derselben Stelle um einige dB, deshalb großzügig.
MOVED_DB = 10
FRITZ_AGE_S = 180  # bei der Meldung höchstens so alte Werte der FRITZ!Box nehmen, sonst neu abfragen


def folder(data_root: Path) -> Path:
    return data_root / "findbar"


def mac_of(device_key: str | None) -> str | None:
    """MAC aus dem Geräteschlüssel der Suche (client:<mac>)."""
    kind, _, mac = (device_key or "").partition(":")
    return mac if kind == "client" and len(mac) == 12 else None


def build(req: FindableIn, cells: dict[str, str], mac: str, name: str) -> dict:
    """Meldung aus dem Scan: je Zugangspunkt das stärkste Signal je Band (wie bei Messpunkten)."""
    p = survey_io.make_point("x", SurveyIn(pos=(0, 0), connection=req.connection, scan=req.scan, device=req.device), cells,
                             max_age_s=SCAN_MAX_AGE_S)
    return {"version": 1, "mac": norm_mac(mac), "name": name, "device": req.device, "app_version": req.app_version,
            "t": datetime.now(UTC).isoformat(timespec="seconds"), "still_s": req.still_s, "connected": p.connected,
            "aps": p.aps, "scan_age_s": p.scan_age_s, "n": sum(len(v) for v in p.aps.values())}


def save(data_root: Path, report: dict) -> None:
    d = folder(data_root)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{report['mac']}.tmp"
    tmp.write_text(json.dumps(report, ensure_ascii=False))
    os.replace(tmp, d / f"{report['mac']}.json")


def load(data_root: Path, mac: str | None) -> dict | None:
    path = folder(data_root) / f"{mac}.json"
    if not mac or not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def delete(data_root: Path, mac: str | None) -> bool:
    path = folder(data_root) / f"{mac}.json"
    if not mac or not path.exists():
        return False
    path.unlink()
    return True


def all_reports(data_root: Path) -> dict[str, dict]:
    d = folder(data_root)
    out = {}
    for path in sorted(d.glob("*.json")) if d.exists() else []:
        rep = load(data_root, path.stem)
        if rep:
            out[rep["mac"]] = rep
    return out


def age_h(report: dict, now: datetime | None = None) -> float:
    return ((now or datetime.now(UTC)) - datetime.fromisoformat(report["t"])).total_seconds() / 3600


def usable(report: dict | None, dev: dict | None) -> tuple[bool, str]:
    """Passt die Meldung noch? dev: das Gerät aus der Mesh-Liste (Sicht der FRITZ!Box), None ohne aktuelle Werte."""
    if report is None:
        return False, ""
    if not report.get("n"):
        return False, "Die letzte Meldung des Handys enthält keinen Zugangspunkt des Hauses."
    if len(report.get("aps") or {}) < MIN_APS:
        return False, ("Die letzte Meldung des Handys enthält nur den verbundenen Zugangspunkt; "
                       "damit lässt sich nicht genauer suchen als mit dem Wert der FRITZ!Box.")
    age = age_h(report)
    if age > MAX_AGE_H:
        return False, f"Die letzte Meldung des Handys ist {age:.0f} Stunden alt."
    ap = (report.get("connected") or {}).get("ap")
    if dev and ap and ap != dev.get("ap"):
        return False, "Das Handy hängt inzwischen an einem anderen Zugangspunkt als bei seiner letzten Meldung; es wurde wohl bewegt."
    fr = report.get("fritz") or {}
    if dev and fr.get("rssi") is not None and fr.get("ap") == dev.get("ap") and fr.get("band") == dev.get("band"):
        delta = abs(int(dev["rssi"]) - int(fr["rssi"]))
        if delta > MOVED_DB:
            return False, (f"Das Signal an der FRITZ!Box hat sich seit der Meldung um {delta} dB geändert "
                           f"({fr['rssi']} → {dev['rssi']} dBm); das Handy wurde wohl bewegt.")
    return True, ""


def summary(report: dict) -> dict:
    return {"t": report["t"], "n": report["n"], "still_s": report.get("still_s"), "model": report.get("device"),
            "name": report.get("name"), "aps": report.get("aps") or {}, "connected": report.get("connected")}
