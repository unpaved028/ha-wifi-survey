"""Geführter Ablauf (Ansicht „Start“): Stand des Projekts je Schritt, vom Plan bis zur Auswertung.

Jeder Schritt: {id, title, status ("done", "todo", "optional"), detail, link, action}. Die Reihenfolge folgt dem
Produktziel: Plan hochladen → Stockwerke → Maßstab → Wände erkennen und prüfen → ausrichten → Zugangspunkte und
Geräte platzieren → Hausfläche prüfen → messen → Auswertung.
"""

from __future__ import annotations

from . import evaluate as ev
from .catalog import norm_mac
from .models import Project

UNSURE = 0.75   # wie im Editor: automatisch erkannte Wände unter dieser Sicherheit gelten als unsicher


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _names(floors) -> str:
    names = [f.name for f in floors]
    return ", ".join(names[:4]) + (f" und {len(names) - 4} weitere" if len(names) > 4 else "")


def steps(project: Project, m: dict | None) -> list[dict]:
    floors = sorted(project.floors, key=lambda f: (f.level, f.name))
    out = []

    def add(sid, title, status, detail, link=None, action=None):
        out.append({"id": sid, "title": title, "status": status, "detail": detail, "link": link, "action": action})

    n_pages = sum(len(p.pages) for p in project.plans)
    add("plan", "Plan hochladen", "done" if project.plans else "todo",
        f"{_n(len(project.plans), 'Plan', 'Pläne')}, {_n(n_pages, 'Seite', 'Seiten')}." if project.plans
        else "Grundriss als PDF oder Bild hochladen (Scan, Foto, Export aus einem Zeichenprogramm).",
        "#/plaene", "Pläne öffnen")
    add("floors", "Stockwerke anlegen", "done" if floors else "todo",
        f"{_n(len(floors), 'Stockwerk', 'Stockwerke')}: {_names(floors)}." if floors
        else "Auf der Planseite je Stockwerk einen Ausschnitt ziehen (Taste C) und benennen.",
        "#/plaene", "Pläne öffnen")
    if not floors:
        return out

    missing = [f for f in floors if not f.scale]
    add("scale", "Maßstab setzen", "todo" if missing else "done",
        f"Ohne Maßstab: {_names(missing)}. Werkzeug „Maßstab“ (M): zwei Punkte einer Bemaßung anklicken, Länge eingeben."
        if missing else "Alle Stockwerke haben einen Maßstab.",
        f"#/stockwerk/{missing[0].id}" if missing else None, f"{missing[0].name} öffnen" if missing else None)

    no_walls = [f for f in floors if not f.walls]
    unsure = [(f, sum(1 for w in f.walls if w.source == "auto" and w.confidence is not None and w.confidence < UNSURE))
              for f in floors]
    worst = max(unsure, key=lambda x: x[1])
    n_walls = sum(len(f.walls) for f in floors)
    if no_walls:
        add("walls", "Wände erkennen und prüfen", "todo",
            f"Ohne Wände: {_names(no_walls)}. Im Stockwerk „Wände erkennen“ drücken, dann korrigieren.",
            f"#/stockwerk/{no_walls[0].id}", f"{no_walls[0].name} öffnen")
    else:
        n_unsure = sum(n for _, n in unsure)
        add("walls", "Wände erkennen und prüfen", "todo" if n_unsure else "done",
            f"{n_walls} Wände, davon {n_unsure} unsicher (orange; Taste N springt zur nächsten)." if n_unsure
            else f"{n_walls} Wände, keine unsicheren mehr. Material und Dicke prüfen (z. B. „Außenwände“ auswählen).",
            f"#/stockwerk/{worst[0].id}" if n_unsure else None, f"{worst[0].name} öffnen" if n_unsure else None)

    scaled = [f for f in floors if f.scale]
    if len(floors) > 1:
        groups = ev._groups(scaled)
        loose = len(set(groups.values())) > 1 or len(scaled) < len(floors)
        add("align", "Stockwerke ausrichten", "todo" if loose else "done",
            "Stockwerke übereinanderlegen (Punktpaare), damit Signale durch die Decken zählen."
            if loose else "Alle Stockwerke liegen in einem gemeinsamen System.",
            "#/ausrichten", "Ausrichten öffnen")

    placed = {d.key: f for f in floors for d in f.devices}
    aps = [k for f in floors for d in f.devices if d.kind == "ap" for k in [d.key]]
    measured_aps = [f"ap:{norm_mac(a.get('mac'))}" for a in (m or {}).get("access_points", [])]
    unplaced = [k for k in measured_aps if k not in placed]
    names = {f"ap:{norm_mac(a.get('mac'))}": a.get("name") for a in (m or {}).get("access_points", [])}
    first = scaled[0] if scaled else floors[0]
    if not aps:
        detail = ("Router und Repeater mit dem Werkzeug „Geräte“ (G) auf den Plan setzen: aus dem Messlauf der "
                  "FRITZ!Box oder als eigene Geräte.")
        status = "todo"
    elif unplaced:
        detail = f"{len(aps)} platziert, noch nicht: {', '.join(names.get(k) or k for k in unplaced)}."
        status = "todo"
    else:
        detail = f"{_n(len(aps), 'Zugangspunkt', 'Zugangspunkte')} platziert."
        status = "done"
    add("aps", "Router und Repeater platzieren", status, detail, f"#/stockwerk/{first.id}", "Geräte setzen")

    n_dev = sum(1 for f in floors for d in f.devices if d.kind != "ap")
    n_meas = len((m or {}).get("shellys", [])) + len((m or {}).get("clients", []))
    add("devices", "Geräte platzieren", "done" if n_dev else "optional",
        f"{n_dev} Geräte platziert" + (f", im Messlauf {n_meas} WLAN-Geräte." if n_meas else ".") +
        " Platzierte Geräte mit Messwerten eichen das Modell und bekommen Hinweise." if n_dev
        else "Optional: Shellys, Fernseher, Kameras … platzieren. Mit Messwerten eichen sie das Modell.",
        f"#/stockwerk/{first.id}", "Geräte setzen")

    guessed = []
    for f in scaled:
        try:
            if ev.floor_area(f)["source"] == "hull":
                guessed.append(f)
        except ValueError:
            pass
    add("area", "Hausfläche prüfen", "todo" if guessed else "done",
        f"Geschätzt (Außenwände fehlen): {_names(guessed)}. Werkzeug „Hausfläche“ (H): Vorschlag übernehmen oder Umriss zeichnen."
        if guessed else "Die Hausfläche folgt den Außenwänden oder einem eigenen Umriss.",
        f"#/stockwerk/{guessed[0].id}" if guessed else None, f"{guessed[0].name} öffnen" if guessed else None)

    n_survey = sum(len(f.survey) for f in floors)
    n_found = sum(len(f.found) for f in floors)
    without = [f for f in scaled if not f.survey]
    when = (m or {}).get("timestamp")
    parts = []
    if when:
        parts.append(f"Messlauf vom {when[8:10]}.{when[5:7]}.{when[:4]}")
    parts.append(f"{n_survey} Messpunkte vom Handy" + (f", {n_found} Fundorte" if n_found else ""))
    if without and n_survey:
        parts.append(f"ohne Messpunkte: {_names(without)}")
    add("measure", "Messen", "done" if n_survey and not without else "optional",
        "; ".join(parts) + ". Messpunkte eichen das Modell; mit der Android-App in der Ansicht „Messen“.",
        f"#/messen/{(without or scaled or floors)[0].id}", "Messen öffnen")

    add("evaluate", "Auswertung ansehen", "optional",
        "Karte je Stockwerk und Band, Abdeckung, Hinweise, Simulation und Empfehlung für bessere Plätze.",
        "#/auswertung", "Auswertung öffnen")
    return out
