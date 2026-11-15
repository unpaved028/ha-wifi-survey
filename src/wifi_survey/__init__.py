"""wifi-survey: WLAN-Ausleuchtung für FRITZ!Box-Mesh mit Repeatern."""

from __future__ import annotations

import argparse
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("wifi-survey")
except PackageNotFoundError:   # ohne Installation, z. B. direkt aus dem Quellordner
    __version__ = "0"


def _summary(result: dict) -> str:
    lines = [f"Messlauf {result['timestamp']}"]
    lines.append("Zugangspunkte:")
    for ap in result["access_points"]:
        cells = ", ".join(f"{c['band']} GHz Kanal {c['channel']}" for c in ap["cells"])
        up = ap["uplink"]["type"] if ap.get("uplink") else "-"
        n = sum(1 for c in result["clients"] if c["ap"] == ap["name"])
        lines.append(f"  {ap['name']:<14} {ap['role']:<6} Anbindung {up:<4} Clients {n:>3}  {cells}")
    weak = sorted((c for c in result["clients"] if c["rcpi"] is not None and c["rcpi"] <= -70), key=lambda c: c["rcpi"])
    lines.append(f"Schwache Clients (<= -70 dBm): {len(weak)}")
    for c in weak:
        lines.append(f"  {c['rcpi']:>4} dBm  {c['name']}  an {c['ap']} ({c['cell']})")
    scanned = [s for s in result["shellys"] if s.get("scan")]
    lines.append(f"Shellys: {len(result['shellys'])} von {result['shelly_candidates']} erreichbar, {len(scanned)} mit Scan")
    sticky = _sticky_shellys(result)
    lines.append(f"Shellys mit deutlich besserem Zugangspunkt in Reichweite (>= {STICKY_MARGIN_DB} dB): {len(sticky)}")
    for s in sticky:
        lines.append(f"  {s['id']}: {s['rssi']} dBm an {s['ap']}, {s['best_rssi']} dBm an {s['best_ap']} möglich")
    return "\n".join(lines)


STICKY_MARGIN_DB = 6


def _sticky_shellys(result: dict) -> list[dict]:
    cell_ap = {c["bssid"]: ap["name"] for ap in result["access_points"] for c in ap["cells"]}
    out = []
    for s in result["shellys"]:
        st, scan = s.get("status") or {}, s.get("scan") or []
        if st.get("rssi") is None or not st.get("bssid"):
            continue
        own_ap = cell_ap.get(st["bssid"].upper(), st["bssid"])
        others = [n for n in scan if cell_ap.get(n["bssid"].upper(), "?") not in (own_ap, "?")]
        if not others:
            continue
        best = max(others, key=lambda n: n["rssi"])
        if best["rssi"] - st["rssi"] >= STICKY_MARGIN_DB:
            out.append({"id": s["id"], "rssi": st["rssi"], "ap": own_ap,
                        "best_rssi": best["rssi"], "best_ap": cell_ap[best["bssid"].upper()]})
    return sorted(out, key=lambda x: x["rssi"] - x["best_rssi"])


def main() -> None:
    parser = argparse.ArgumentParser(prog="wifi-survey", description="WLAN-Ausleuchtung für FRITZ!Box-Mesh")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_collect = sub.add_parser("collect", help="Messlauf durchführen und speichern")
    p_collect.add_argument("--no-scan", action="store_true", help="keine WLAN-Scans auf den Shellys")
    p_sum = sub.add_parser("summary", help="Zusammenfassung eines gespeicherten Messlaufs")
    p_sum.add_argument("file", type=Path)
    p_serve = sub.add_parser("serve", help="Plan-Editor (Web-App und API) starten")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8770)
    p_serve.add_argument("--no-access-log", action="store_true", help="keine Zeile je Anfrage im Protokoll (HA-App)")
    p_imp = sub.add_parser("import-plan", help="Plan (PDF oder Bild) ins Projekt übernehmen")
    p_imp.add_argument("file", type=Path)
    args = parser.parse_args()

    if args.cmd == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info", access_log=not args.no_access_log)
        return
    if args.cmd == "import-plan":
        from .api import import_plan_file
        from .config import project_dir
        from .store import Store

        plan = import_plan_file(Store(project_dir()), args.file)
        print(f"Plan {plan.id} ({plan.name}): {len(plan.pages)} Seite(n), "
              + ", ".join(f"{p.width:.0f}×{p.height:.0f}" for p in plan.pages))
        return

    if args.cmd == "collect":
        from .collect import run, save

        result = run(scan=not args.no_scan)
        path = save(result)
        print(_summary(result))
        print(f"Gespeichert: {path}")
    elif args.cmd == "summary":
        print(_summary(json.loads(args.file.read_text())))
