"""Datenmodell des Plan-Editors (API und Speicherung).

Koordinaten:
- Seitenkoordinaten (Plan): PDF in Punkt (1/72 Zoll), Bilder in Pixeln des Originals.
- Stockwerkbild: Pixel des gerenderten Ausschnitts (x nach rechts, y nach unten).
  Umrechnung Seite -> Bild: (p - crop.xy) * render_scale.
- Gebäude (Meter): Bildpixel / px_per_m, dann Drehung rot_deg um (0, 0), dann Verschiebung.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Point = tuple[float, float]
RSSI_VALID = (-110, -10)  # WLAN-Signale liegen praktisch immer dazwischen; Android meldet 0 oder −127 als Platzhalter


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class Material(BaseModel):
    id: str
    name: str
    color: str


MATERIALS: list[Material] = [
    Material(id="hochlochziegel", name="Hochlochziegel", color="#c0392b"),
    Material(id="beton", name="Beton", color="#839192"),
    Material(id="stahlbeton", name="Stahlbeton", color="#566573"),
    Material(id="trockenbau", name="Trockenbau", color="#d4ac0d"),
    Material(id="glas", name="Glas / Fenster", color="#2e86c1"),
    Material(id="holz", name="Holz / Tür", color="#935116"),
    Material(id="metall", name="Metall", color="#1c2833"),
    Material(id="kunststoff", name="Kunststoff", color="#48c9b0"),
    Material(id="sonstiges", name="Sonstiges", color="#7d3c98"),
]
MATERIAL_IDS = {m.id for m in MATERIALS}
DEFAULT_MATERIAL = "hochlochziegel"  # im Testhaus sind alle Wände aus Hochlochziegel, in Deutschland häufig


class Page(BaseModel):
    index: int
    width: float   # Seitenkoordinaten
    height: float


class Plan(BaseModel):
    id: str
    name: str
    kind: Literal["pdf", "image"]
    filename: str
    pages: list[Page]
    created: datetime = Field(default_factory=now)


class Crop(BaseModel):
    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)


class Scale(BaseModel):
    a: Point
    b: Point
    length_m: float = Field(gt=0)
    px_per_m: float = 0.0

    @model_validator(mode="after")
    def _compute(self) -> Scale:
        dist = math.dist(self.a, self.b)
        if dist <= 0:
            raise ValueError("Die beiden Punkte des Maßstabs dürfen nicht zusammenfallen")
        self.px_per_m = round(dist / self.length_m, 4)
        return self


class Wall(BaseModel):
    id: str
    a: Point
    b: Point
    thickness_px: float = Field(gt=0)
    material: str = DEFAULT_MATERIAL
    source: Literal["auto", "manual"] = "manual"
    confidence: float | None = None  # nur bei automatisch erkannten Wänden

    @model_validator(mode="after")
    def _check(self) -> Wall:
        if self.material not in MATERIAL_IDS:
            raise ValueError(f"Unbekanntes Material: {self.material}")
        return self


class Placement(BaseModel):
    """Ein Gerät (Zugangspunkt, Shelly, sonstiger WLAN-Client) auf dem Stockwerkplan."""

    id: str
    # stabiler Schlüssel aus dem Gerätekatalog, z. B. "shelly:021901898fdc"; eigene Geräte ohne Messlauf: "manual:<id>"
    key: str = Field(min_length=3, max_length=80)
    kind: Literal["ap", "shelly", "client", "other"] = "other"
    label: str = Field(min_length=1, max_length=80)
    pos: Point
    # nur für eigene Zugangspunkte (Planung ohne Messlauf); sonst stehen Rolle und Anbindung im Messlauf
    role: Literal["master", "slave"] | None = None     # master = Router am Internetanschluss
    uplink: Literal["WLAN", "LAN"] | None = None
    # eigene Zugangspunkte: zugeordnete Netze (BSSID, 12 Hex-Zeichen) für Rundgänge ohne FRITZ!Box
    bssids: list[str] = Field(default_factory=list, max_length=32)


class SurveyPoint(BaseModel):
    """Messpunkt eines Rundgangs mit dem Handy (Sicht des Handys, Signal in dBm).

    aps: je Zugangspunkt das stärkste Signal je Band ("2.4", "5", "6"), aus dem WLAN-Scan und der
    Verbindung. others: fremde Netze ohne Namen und Adresse, nur Band, Kanal und Signal.
    """

    id: str
    pos: Point
    t: datetime = Field(default_factory=now)
    connected: dict | None = None
    aps: dict[str, dict[str, int]] = Field(default_factory=dict)
    others: list[dict] = Field(default_factory=list)
    scan_age_s: float | None = None
    device: str = ""
    found: str | None = None             # Fundort, zu dem der Messpunkt gehört (Scan im Hintergrund, Entscheidung 0010)

    @field_validator("aps")
    @classmethod
    def _drop_placeholders(cls, v: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        """Platzhalter wie 0 dBm aus älteren Rundgängen fallen weg; sonst gälten sie in der Anzeige als stärkster Wert."""
        kept = {k: {b: x for b, x in bands.items() if RSSI_VALID[0] <= x <= RSSI_VALID[1]} for k, bands in v.items()}
        return {k: bands for k, bands in kept.items() if bands}


class FoundPoint(BaseModel):
    """Fundort eines gesuchten Geräts (Ansicht „Suchen“): wo es wirklich lag, mit dem Signal, mit dem
    sein Zugangspunkt es bei der Suche empfing (Sicht der FRITZ!Box). Geht als Messpunkt in die Eichung ein.
    """

    id: str
    pos: Point
    t: datetime = Field(default_factory=now)
    device: str                          # Schlüssel wie im Gerätekatalog, z. B. client:<mac>
    label: str = ""
    ap: str                              # Zugangspunkt, an dem das Gerät hing
    band: Literal["2.4", "5", "6"] | None = None
    rssi: int = Field(ge=-127, le=0)
    measured_at: str | None = None       # Zeitpunkt der Signalwerte (FRITZ!Box)
    # Wie gut lag die Schätzung (berechnet beim Speichern, mit dem Modell ohne diesen Fundort)?
    estimate_floor: str | None = None    # wahrscheinlichstes Stockwerk (ID)
    floor_share: int | None = None       # Wahrscheinlichkeit für das Stockwerk des Fundorts (%)
    in_region: bool | None = None        # Fundort im wahrscheinlichen Bereich (50 %)?
    error_m: float | None = None         # Abstand zur wahrscheinlichsten Stelle (Gebäudemeter, mit Geschosshöhe)
    room_rank: int | None = None         # Platz des richtigen Raums in der Liste der Suche (1 = vorne, Entscheidung 0014)


class Transform(BaseModel):
    dx_m: float = 0.0
    dy_m: float = 0.0
    rot_deg: float = 0.0


class RoomLabel(BaseModel):
    """Name eines Raums vom Anwender (Entscheidung 0014): gilt für den Raum, in dem pos liegt (Bildpixel).
    Räume selbst entstehen aus den Wänden; das Schild bleibt stehen, wenn sich die Wände ändern."""

    pos: Point
    name: str = Field(min_length=1, max_length=40)


class RoomLabelSet(BaseModel):
    labels: list[RoomLabel] = Field(default_factory=list, max_length=100)


class Floor(BaseModel):
    id: str
    name: str
    level: int = 0
    plan_id: str
    page: int = 0
    crop: Crop
    render_scale: float           # Bildpixel je Seiteneinheit
    image_w: int
    image_h: int
    scale: Scale | None = None
    walls: list[Wall] = Field(default_factory=list)
    devices: list[Placement] = Field(default_factory=list)
    # vom Anwender gelöschte Vorschläge: eine neue Erkennung schlägt sie nicht wieder vor
    ignored: list[Wall] = Field(default_factory=list)
    survey: list[SurveyPoint] = Field(default_factory=list)
    found: list[FoundPoint] = Field(default_factory=list)
    transform: Transform = Field(default_factory=Transform)
    reference_floor: str | None = None
    ceiling_thickness_cm: float | None = None
    # Hausfläche vom Anwender (Umrisse in Bildpixeln); ohne sie bestimmt die Auswertung sie selbst (Entscheidung 0005)
    outline: list[list[Point]] | None = None
    # eigene Namen für Räume (Entscheidung 0014); ohne sie heißen Räume nach den Bereichen der Geräte in HA
    room_labels: list[RoomLabel] = Field(default_factory=list, max_length=100)
    updated: datetime = Field(default_factory=now)


class Project(BaseModel):
    version: int = 1
    plans: list[Plan] = Field(default_factory=list)
    floors: list[Floor] = Field(default_factory=list)
    # Beispielhaus (Paket A17): keine Abfragen von FRITZ!Box und Shellys, Messlauf aus dem Beispiel
    demo: bool = False

    def plan(self, plan_id: str) -> Plan | None:
        return next((p for p in self.plans if p.id == plan_id), None)

    def floor(self, floor_id: str) -> Floor | None:
        return next((f for f in self.floors if f.id == floor_id), None)


# --- Anfragen ------------------------------------------------------------------------------

class FloorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    level: int = 0
    plan_id: str
    page: int = 0
    crop: Crop


class FloorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    level: int | None = None
    crop: Crop | None = None
    transform: Transform | None = None
    reference_floor: str | None = None
    ceiling_thickness_cm: float | None = None


class BssidSet(BaseModel):
    """Netze (BSSIDs) eines eigenen Zugangspunkts, aus dem Scan des Handys zugeordnet."""

    bssids: list[str] = Field(default_factory=list, max_length=32)


class OutlineSet(BaseModel):
    """Hausfläche eines Stockwerks: ein oder mehrere Umrisse (Bildpixel); None = wieder automatisch."""

    polygons: list[list[Point]] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _check(self) -> OutlineSet:
        for poly in self.polygons or []:
            if not 3 <= len(poly) <= 500:
                raise ValueError("Ein Umriss braucht mindestens 3 und höchstens 500 Ecken")
        if self.polygons is not None and not self.polygons:
            self.polygons = None
        return self


class ScaleSet(BaseModel):
    a: Point
    b: Point
    length_m: float = Field(gt=0)


class DetectRequest(BaseModel):
    mode: Literal["replace_auto", "replace_all", "add"] = "replace_auto"
    snap_thickness: bool = True
    style: Literal["auto", "filled", "outline"] = "auto"   # Wände im Plan: erkennen, gefüllt/schraffiert, nur Umriss


class DetectResponse(BaseModel):
    floor: Floor
    added: int
    removed: int
    stats: dict


class SimPlace(BaseModel):
    floor_id: str
    pos: Point


class SimAdded(SimPlace):
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(default="Neuer Repeater", min_length=1, max_length=80)


class SimulationRequest(BaseModel):
    """Aufstellung zum Durchrechnen: Zugangspunkte verschoben, abgeschaltet oder ergänzt."""

    floor_id: str | None = None          # Stockwerk, für das die Karte geliefert wird
    moved: dict[str, SimPlace] = Field(default_factory=dict)
    off: list[str] = Field(default_factory=list)
    added: list[SimAdded] = Field(default_factory=list, max_length=5)


class RecommendRequest(BaseModel):
    movable: list[str] = Field(default_factory=list)   # Schlüssel der Zugangspunkte, die wandern dürfen
    add: int = Field(default=0, ge=0, le=2)            # so viele zusätzliche Repeater vorschlagen



class WifiConnection(BaseModel):
    """Verbundener Zugangspunkt aus Sicht des Handys (Android: WifiInfo)."""

    bssid: str = ""
    ssid: str = ""
    rssi: int = Field(ge=-127, le=0)
    frequency: int = Field(default=0, ge=0, le=8000)
    link_mbps: int | None = None


class WifiReading(BaseModel):
    """Ein Eintrag aus dem WLAN-Scan des Handys."""

    bssid: str = ""
    ssid: str = ""
    rssi: int = Field(ge=-127, le=0)
    frequency: int = Field(ge=0, le=8000)
    age_ms: int | None = None


class SurveyIn(BaseModel):
    pos: Point
    connection: WifiConnection | None = None
    scan: list[WifiReading] = Field(default_factory=list, max_length=500)
    device: str = Field(default="", max_length=120)


class FindableIn(BaseModel):
    """Meldung der Android-App im Hintergrundmodus „findbar“ (Entscheidung 0010): Scan des ruhenden Handys."""

    device: str = Field(default="", max_length=120)          # Modell, z. B. „Pixel 9“
    app_version: str = Field(default="", max_length=20)
    connection: WifiConnection | None = None
    scan: list[WifiReading] = Field(default_factory=list, max_length=500)
    still_s: int | None = Field(default=None, ge=0)          # so lange lag das Handy schon am selben Platz


class LocateRequest(BaseModel):
    device: str = Field(max_length=80)
    basis: Literal["auto", "fritzbox"] = "auto"    # auto: eigener Scan des Handys, wenn vorhanden und passend


class LocateReading(BaseModel):
    ap: str = Field(max_length=40)
    band: Literal["2.4", "5", "6"] | None = None
    rssi: int = Field(ge=-127, le=0)
    measured_at: str | None = Field(default=None, max_length=40)


class FoundIn(BaseModel):
    device: str = Field(max_length=80)
    label: str = Field(default="", max_length=120)
    pos: Point
    reading: LocateReading
    force: bool = False       # trotz unverändertem Wert seit dem letzten Fundort speichern
    scan_t: str | None = Field(default=None, max_length=40)   # Zeit der Meldung „findbar“, mit der gesucht wurde
