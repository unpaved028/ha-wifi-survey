"""Pfade und Grundeinstellungen."""

from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("WIFI_SURVEY_DATA", PROJECT_ROOT / "data"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
# Einstellungen der Home-Assistant-App (vom Supervisor geschrieben); außerhalb der App gibt es die Datei nicht
OPTIONS_FILE = Path(os.environ.get("WIFI_SURVEY_OPTIONS", "/data/options.json"))

# Übliche Mauerwerksdicken (cm); erkannte Wände werden nach der Kalibrierung darauf gerundet
THICKNESS_CLASSES_CM = (11.5, 17.5, 24.0, 30.0, 36.5)
THICKNESS_SNAP_TOLERANCE = 0.3  # relativ: höchstens 30 % Abweichung zur nächsten Klasse

FLOOR_DPI = 200                 # Auflösung der Stockwerkbilder aus PDF-Plänen
FLOOR_MAX_PX = 4000             # längste Bildseite; bei Bedarf wird die Auflösung reduziert
PREVIEW_DPI = 72                # Übersichtsbild einer PDF-Seite: 1 px = 1 pt


def project_dir() -> Path:
    return DATA_DIR / "projekt"


def in_ha_app() -> bool:
    """Läuft als App unter dem Supervisor von Home Assistant (Token kommt vom Supervisor)."""
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


def app_options() -> dict:
    """Einstellungen aus der App-Konfiguration in Home Assistant, sonst leer."""
    try:
        data = json.loads(OPTIONS_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
