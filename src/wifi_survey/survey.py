"""Rundgang mit dem Handy: WLAN-Werte des Handys den Zugangspunkten zuordnen.

Die Android-App liefert den verbundenen Zugangspunkt (BSSID, Signal, Frequenz) und den WLAN-Scan.
Zugangspunkte werden über die BSSIDs aus dem letzten Messlauf erkannt; weitere Netze desselben
Geräts (Gastnetz, zusätzliche SSIDs) über die ersten fünf Bytes der Adresse. Fremde Netze werden
ohne Namen und Adresse gespeichert, nur Band, Kanal, Anzahl und stärkstes Signal.
"""

from __future__ import annotations

from statistics import median

from .catalog import norm_mac
from .models import RSSI_VALID, SurveyIn, SurveyPoint

MAX_SCAN_AGE_S = 60     # ältere Scan-Ergebnisse stammen vermutlich von einem anderen Platz
MAX_OTHERS = 40


def valid_rssi(v) -> bool:
    """Plausibles Signal in dBm? 0 dBm kommt im Scan von Android vor und würde als stärkster Wert
    alle echten Werte desselben Zugangspunkts verdrängen."""
    return v is not None and RSSI_VALID[0] <= v <= RSSI_VALID[1]


def band_of(freq: int) -> str | None:
    if 2400 <= freq <= 2500:
        return "2.4"
    if 4900 <= freq <= 5900:
        return "5"
    if 5925 <= freq <= 7125:
        return "6"
    return None


def channel_of(freq: int) -> int | None:
    if freq == 2484:
        return 14
    if 2412 <= freq <= 2472:
        return (freq - 2407) // 5
    if 5000 <= freq <= 5900:
        return (freq - 5000) // 5
    if 5955 <= freq <= 7115:
        return (freq - 5950) // 5
    return None


def ap_cells(m: dict | None) -> dict[str, str]:
    """BSSID (und Geräteadresse) -> Schlüssel des Zugangspunkts aus dem letzten Messlauf."""
    out = {}
    for ap in (m or {}).get("access_points", []):
        key = f"ap:{norm_mac(ap.get('mac'))}"
        out[norm_mac(ap.get("mac"))] = key
        for c in ap.get("cells", []):
            out[norm_mac(c.get("bssid"))] = key
    return out


def placed_cells(project) -> dict[str, str]:
    """BSSID -> Schlüssel für Netze, die der Anwender eigenen Zugangspunkten zugeordnet hat (ohne FRITZ!Box)."""
    return {norm_mac(b): d.key for f in project.floors for d in f.devices if d.kind == "ap" for b in d.bssids}


def match(bssid: str, cells: dict[str, str]) -> str | None:
    """Zugangspunkt zu einer BSSID: genau, sonst über die ersten fünf Bytes, wenn eindeutig."""
    b = norm_mac(bssid)
    if len(b) != 12 or b == "020000000000":      # Android verbirgt die BSSID ohne Berechtigung
        return None
    if b in cells:
        return cells[b]
    hits = {key for c, key in cells.items() if c[:10] == b[:10]}
    return hits.pop() if len(hits) == 1 else None


def make_point(pid: str, req: SurveyIn, cells: dict[str, str], max_age_s: float = MAX_SCAN_AGE_S) -> SurveyPoint:
    aps: dict[str, dict[str, int]] = {}
    others: dict[tuple[str, int | None], list[int]] = {}
    ages = []
    for r in req.scan:
        band = band_of(r.frequency)
        if band is None or not valid_rssi(r.rssi) or (r.age_ms is not None and r.age_ms > max_age_s * 1000):
            continue
        if r.age_ms is not None:
            ages.append(r.age_ms / 1000)
        key = match(r.bssid, cells)
        if key:
            cur = aps.setdefault(key, {})
            cur[band] = max(cur.get(band, -999), r.rssi)
        else:
            others.setdefault((band, channel_of(r.frequency)), []).append(r.rssi)
    connected = None
    c = req.connection
    if c and valid_rssi(c.rssi):
        band = band_of(c.frequency)
        key = match(c.bssid, cells)
        connected = {"ap": key, "band": band, "rssi": c.rssi, "link_mbps": c.link_mbps}
        if key and band:   # die Verbindung ist frischer als der Scan
            aps.setdefault(key, {})[band] = c.rssi
    nb = sorted(({"band": b, "channel": ch, "count": len(v), "rssi": max(v)} for (b, ch), v in others.items()),
                key=lambda x: -x["rssi"])[:MAX_OTHERS]
    return SurveyPoint(id=pid, pos=req.pos, connected=connected, aps=aps, others=nb,
                       scan_age_s=round(median(ages), 1) if ages else None, device=req.device)
