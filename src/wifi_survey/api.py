"""HTTP-API des Plan-Editors (FastAPI). OpenAPI-Beschreibung unter /api/docs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import cv2
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import __version__, haapp
from . import catalog as catalog_io
from . import demo as demo_io
from . import evaluate as evaluate_io
from . import findable as findable_io
from . import fritz as fritz_io
from . import locate as locate_io
from . import plans as plan_io
from . import progress as progress_io
from . import rooms as rooms_io
from . import simulate as simulate_io
from . import survey as survey_io
from . import transfer as transfer_io
from .config import (
    STATIC_DIR,
    THICKNESS_CLASSES_CM,
    THICKNESS_SNAP_TOLERANCE,
    in_ha_app,
    project_dir,
)
from .models import (
    MATERIALS,
    BssidSet,
    Crop,
    DetectRequest,
    DetectResponse,
    FindableIn,
    Floor,
    FloorCreate,
    FloorUpdate,
    FoundIn,
    FoundPoint,
    LocateRequest,
    Material,
    OutlineSet,
    Placement,
    Plan,
    Project,
    RecommendRequest,
    RoomLabelSet,
    Scale,
    ScaleSet,
    SimulationRequest,
    SurveyIn,
    SurveyPoint,
    Wall,
    now,
)
from .store import Store, new_id
from .topology import covered_share, exterior_walls
from .walls import DetectParams, detect

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
LOCATE_MAX_AGE_S = 60      # so lange gilt eine Mesh-Liste für die Geräteliste, danach neu abfragen
LOCATE_SEARCH_AGE_S = 15   # die Suche selbst braucht frische Werte (Gerät eben umgelegt)


def snap_thickness_px(px: float, px_per_m: float) -> float:
    """Rundet eine Dicke auf die nächste übliche Mauerwerksdicke, wenn sie nah genug liegt."""
    cm = px / px_per_m * 100
    best = min(THICKNESS_CLASSES_CM, key=lambda c: abs(c - cm))
    if abs(best - cm) <= THICKNESS_SNAP_TOLERANCE * best:
        return round(best / 100 * px_per_m, 2)
    return px


def _reproject(floor: Floor, old_crop: Crop, old_s: float, new_crop: Crop, new_s: float) -> None:
    """Rechnet Wände und Maßstab nach einer Änderung des Ausschnitts in neue Bildpixel um."""
    def conv(p):
        px = old_crop.x + p[0] / old_s
        py = old_crop.y + p[1] / old_s
        return (round((px - new_crop.x) * new_s, 2), round((py - new_crop.y) * new_s, 2))

    factor = new_s / old_s
    for w in [*floor.walls, *floor.ignored]:
        w.a, w.b = conv(w.a), conv(w.b)
        w.thickness_px = round(w.thickness_px * factor, 2)
    for item in [*floor.devices, *floor.survey, *floor.found]:   # Geräte, Messpunkte und Fundorte wandern mit
        item.pos = conv(item.pos)
    if floor.outline:
        floor.outline = [[conv(p) for p in pg] for pg in floor.outline]
    for rl in floor.room_labels:
        rl.pos = conv(rl.pos)
    if floor.scale:
        floor.scale = Scale(a=conv(floor.scale.a), b=conv(floor.scale.b), length_m=floor.scale.length_m)


def create_app(store: Store | None = None) -> FastAPI:
    store = store or Store(project_dir())
    data_root = store.root.parent          # neben dem Projekt: messungen/, findbar/
    app = FastAPI(title="wifi-survey", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.get("/api/info")
    def info(request: Request) -> dict:
        """Version und Betriebsart; als HA-App die direkte Adresse im Heimnetz (für die Android-App)."""
        return {"version": __version__, "ha_app": in_ha_app(), "ingress": "x-ingress-path" in request.headers,
                "direct_url": haapp.direct_url()}

    @app.get("/api/project/export")
    def project_export() -> FileResponse:
        """Projekt als ZIP: Pläne, Stockwerke mit Wänden, Geräten und Messpunkten, dazu die Messläufe."""
        path = transfer_io.export_zip(store, __version__)
        return FileResponse(path, media_type="application/zip", filename=f"wifi-survey-{datetime.now():%Y-%m-%d}.zip",
                            background=BackgroundTask(path.unlink, missing_ok=True))

    @app.post("/api/project/import")
    def project_import(file: UploadFile = File(...)) -> dict:
        """Ersetzt das Projekt durch eine Exportdatei. Das bisherige wird unter sicherungen/ aufbewahrt."""
        try:
            return transfer_io.import_zip(file.file, store)
        except (ValueError, zipfile.BadZipFile) as e:
            raise HTTPException(400, f"Import fehlgeschlagen: {e}") from e

    def get_floor(project: Project, floor_id: str) -> Floor:
        floor = project.floor(floor_id)
        if floor is None:
            raise HTTPException(404, "Stockwerk nicht gefunden")
        return floor

    def plan_source(plan: Plan) -> Path:
        return store.plan_dir(plan.id) / plan.filename

    def render(project: Project, floor: Floor) -> None:
        plan = project.plan(floor.plan_id)
        if plan is None:
            raise HTTPException(404, "Plan nicht gefunden")
        if not 0 <= floor.page < len(plan.pages):
            raise HTTPException(400, "Seite existiert nicht")
        page = plan.pages[floor.page]
        try:
            floor.crop = plan_io.clamp_crop(floor.crop, page)
            s, w, h = plan_io.render_floor(plan_source(plan), plan.kind, page, floor.crop, store.floor_image(floor.id))
        except plan_io.PlanError as e:
            raise HTTPException(400, str(e)) from e
        floor.render_scale, floor.image_w, floor.image_h = s, w, h

    @app.get("/api/progress")
    def progress() -> dict:
        """Geführter Ablauf: Stand des Projekts je Schritt (Ansicht „Start“)."""
        m = catalog_io.latest_measurement(store.root.parent / "messungen")
        st = progress_io.steps(store.load(), m)
        return {"steps": st, "done": sum(1 for x in st if x["status"] == "done"),
                "todo": sum(1 for x in st if x["status"] == "todo")}

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/materials", response_model=list[Material])
    def materials() -> list[Material]:
        return MATERIALS

    @app.get("/api/thickness-classes")
    def thickness_classes() -> dict:
        return {"classes_cm": list(THICKNESS_CLASSES_CM), "tolerance": THICKNESS_SNAP_TOLERANCE}

    @app.get("/api/project", response_model=Project)
    def get_project() -> Project:
        return store.load()

    # --- Pläne --------------------------------------------------------------------------

    @app.post("/api/plans", response_model=Plan)
    async def upload_plan(file: UploadFile = File(...)) -> Plan:
        name = Path(file.filename or "plan").name
        try:
            kind = plan_io.kind_for(name)
        except plan_io.PlanError as e:
            raise HTTPException(400, str(e)) from e
        plan_id = new_id("p")
        target_dir = store.plan_dir(plan_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"original{Path(name).suffix.lower()}"
        size = 0
        with target.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    fh.close()
                    shutil.rmtree(target_dir, ignore_errors=True)
                    raise HTTPException(413, "Datei zu groß (höchstens 200 MB)")
                fh.write(chunk)
        try:
            pages = plan_io.import_plan(target, target_dir, kind)
        except plan_io.PlanError as e:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise HTTPException(400, str(e)) from e
        plan = Plan(id=plan_id, name=Path(name).stem, kind=kind, filename=target.name, pages=pages)
        with store.edit() as project:
            project.plans.append(plan)
        return plan

    @app.get("/api/plans/{plan_id}/pages/{index}/preview.png")
    def page_preview(plan_id: str, index: int) -> FileResponse:
        project = store.load()
        plan = project.plan(plan_id)
        if plan is None or not 0 <= index < len(plan.pages):
            raise HTTPException(404, "Seite nicht gefunden")
        return FileResponse(plan_io.preview_path(store.plan_dir(plan_id), index), media_type="image/png")

    @app.delete("/api/plans/{plan_id}")
    def delete_plan(plan_id: str) -> dict:
        with store.edit() as project:
            if project.plan(plan_id) is None:
                raise HTTPException(404, "Plan nicht gefunden")
            if any(f.plan_id == plan_id for f in project.floors):
                raise HTTPException(409, "Plan wird noch von Stockwerken verwendet")
            project.plans = [p for p in project.plans if p.id != plan_id]
        shutil.rmtree(store.plan_dir(plan_id), ignore_errors=True)
        return {"deleted": plan_id}

    # --- Beispielhaus (Paket A17) ----------------------------------------------------------
    @app.post("/api/demo")
    def demo_load() -> dict:
        """Beispielhaus in ein leeres Projekt laden: Plan, Wände, Geräte, Räume, Messpunkte und Messlauf."""
        if store.load().plans or store.load().floors:
            raise HTTPException(409, "Das Beispielhaus lässt sich nur in ein leeres Projekt laden.")
        plan_id = new_id("p")
        target_dir = store.plan_dir(plan_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(target_dir / "original.png"), demo_io.plan_image())
        pages = plan_io.import_plan(target_dir / "original.png", target_dir, "image")
        with store.edit() as project:
            project.plans.append(Plan(id=plan_id, name="Beispielhaus", kind="image", filename="original.png", pages=pages))
            floors = demo_io.floors(plan_id, new_id)
            for f in floors:
                render(project, f)
                project.floors.append(f)
            m = demo_io.fill(project, floors, new_id)
        meas_dir = store.root.parent / "messungen"
        meas_dir.mkdir(parents=True, exist_ok=True)
        (meas_dir / demo_io.measurement_name()).write_text(json.dumps(m, ensure_ascii=False))
        locate_state["snap"] = None
        return {"floors": [f.id for f in floors]}

    @app.delete("/api/demo")
    def demo_end() -> dict:
        """Beispiel beenden: Projekt wieder leer, Planbilder und Messlauf des Beispiels weg."""
        project = store.load()
        if not project.demo:
            raise HTTPException(409, "Das Projekt ist kein Beispielhaus.")
        for p in project.plans:
            shutil.rmtree(store.plan_dir(p.id), ignore_errors=True)
        for f in project.floors:
            store.floor_image(f.id).unlink(missing_ok=True)
        for f in (store.root.parent / "messungen").glob(f"*{demo_io.MEASUREMENT_SUFFIX}"):
            f.unlink()
        with store.edit() as project:
            project.plans, project.floors, project.demo = [], [], False
        locate_state["snap"] = None
        return {"ok": True}

    # --- Stockwerke ---------------------------------------------------------------------

    @app.post("/api/floors", response_model=Floor)
    def create_floor(req: FloorCreate) -> Floor:
        with store.edit() as project:
            floor = Floor(id=new_id("f"), name=req.name, level=req.level, plan_id=req.plan_id, page=req.page,
                          crop=req.crop, render_scale=1.0, image_w=1, image_h=1)
            render(project, floor)
            project.floors.append(floor)
        return floor

    @app.get("/api/floors/{floor_id}", response_model=Floor)
    def read_floor(floor_id: str) -> Floor:
        return get_floor(store.load(), floor_id)

    @app.patch("/api/floors/{floor_id}", response_model=Floor)
    def update_floor(floor_id: str, req: FloorUpdate) -> Floor:
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            changes = req.model_dump(exclude_unset=True)
            ref = changes.get("reference_floor")
            if ref is not None and (ref == floor_id or project.floor(ref) is None):
                raise HTTPException(400, "Ungültiges Bezugsstockwerk")
            for key in ("name", "level", "transform", "reference_floor", "ceiling_thickness_cm"):
                if key in changes:
                    setattr(floor, key, getattr(req, key))
            if req.crop is not None:
                old_crop, old_s = floor.crop, floor.render_scale
                floor.crop = req.crop
                render(project, floor)
                _reproject(floor, old_crop, old_s, floor.crop, floor.render_scale)
            floor.updated = now()
        return floor

    @app.delete("/api/floors/{floor_id}")
    def delete_floor(floor_id: str) -> dict:
        with store.edit() as project:
            get_floor(project, floor_id)
            project.floors = [f for f in project.floors if f.id != floor_id]
            for f in project.floors:
                if f.reference_floor == floor_id:
                    f.reference_floor = None
        store.floor_image(floor_id).unlink(missing_ok=True)
        return {"deleted": floor_id}

    @app.get("/api/floors/{floor_id}/image.png")
    def floor_image(floor_id: str) -> FileResponse:
        get_floor(store.load(), floor_id)
        path = store.floor_image(floor_id)
        if not path.exists():
            raise HTTPException(404, "Bild fehlt")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.put("/api/floors/{floor_id}/scale", response_model=Floor)
    def set_scale(floor_id: str, req: ScaleSet) -> Floor:
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            try:
                floor.scale = Scale(a=req.a, b=req.b, length_m=req.length_m)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            floor.updated = now()
        return floor

    @app.delete("/api/floors/{floor_id}/scale", response_model=Floor)
    def clear_scale(floor_id: str) -> Floor:
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            floor.scale = None
            floor.updated = now()
        return floor

    @app.put("/api/floors/{floor_id}/walls", response_model=Floor)
    def put_walls(floor_id: str, walls: list[Wall]) -> Floor:
        ids = [w.id for w in walls]
        if len(ids) != len(set(ids)):
            raise HTTPException(400, "Wand-IDs sind nicht eindeutig")
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            new_ids = set(ids)
            removed = [w for w in floor.walls if w.source == "auto" and w.id not in new_ids]
            # gelöschte Vorschläge merken; kommt eine Wand zurück (Rückgängig), wieder vergessen
            keep = [w for w in floor.ignored if w.id not in new_ids and w.id not in {r.id for r in removed}]
            floor.ignored = (keep + removed)[-2000:]
            floor.walls = walls
            floor.updated = now()
        return floor

    @app.get("/api/floors/{floor_id}/outline")
    def floor_outline(floor_id: str) -> dict:
        """Hausfläche: eigener Umriss, automatischer Vorschlag, Flächen (ohne Wände) und die Umrisse der
        ausgerichteten Stockwerke, umgerechnet auf dieses Stockwerk (zum Übernehmen)."""
        project = store.load()
        floor = get_floor(project, floor_id)
        if not floor.scale:
            raise HTTPException(409, "Für die Hausfläche braucht das Stockwerk einen Maßstab.")

        def area(f: Floor) -> float | None:
            try:
                return evaluate_io.floor_area(f)["area_m2"]
            except ValueError:   # nichts auf dem Stockwerk
                return None

        auto_floor = floor.model_copy(update={"outline": None})
        auto = evaluate_io.outline_proposal(floor) if floor.walls else {"source": None, "polygons": []}
        b = evaluate_io.Building(project)
        others = []
        for o in b.floors:
            if o.id == floor.id or not b.linked(o, floor):
                continue
            polys = o.outline or (evaluate_io.outline_proposal(o)["polygons"] if o.walls else [])
            if polys:
                others.append({"floor_id": o.id, "name": o.name, "level": o.level, "user": bool(o.outline),
                               "polygons": [[[round(float(x), 1), round(float(y), 1)] for x, y in b.to_px(floor, b.to_m(o, pg))]
                                            for pg in polys]})
        others.sort(key=lambda x: (abs(x["level"] - floor.level), -x["level"]))
        return {"user": floor.outline, "area_m2": area(floor), "auto": {**auto, "area_m2": area(auto_floor)},
                "others": others}

    @app.put("/api/floors/{floor_id}/outline")
    def put_outline(floor_id: str, req: OutlineSet) -> dict:
        """Hausfläche des Stockwerks setzen (Umrisse in Bildpixeln) oder mit null wieder automatisch bestimmen."""
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            floor.outline = [[(round(x, 2), round(y, 2)) for x, y in pg] for pg in req.polygons] if req.polygons else None
            floor.updated = now()
        area = None
        if floor.scale:
            try:
                area = evaluate_io.floor_area(floor)["area_m2"]
            except ValueError:
                pass
        return {"user": floor.outline, "area_m2": area}

    # --- Räume (Entscheidung 0014) ------------------------------------------------------------
    def room_areas(project: Project) -> dict[str, str]:
        """Bereich in Home Assistant je platziertem Shelly: daraus die Namen der Räume."""
        ha = catalog_io.ha_names()
        return {d.key: (ha.get(d.key.split(":", 1)[1]) or {}).get("area", "")
                for f in project.floors for d in f.devices if d.key.startswith("shelly:")}

    def floor_rooms(project: Project, floors: list[Floor]) -> dict[str, dict]:
        areas = room_areas(project)
        out = {}
        for f in floors:
            try:
                out[f.id] = rooms_io.compute(f, areas)
            except ValueError:
                pass   # ohne Maßstab oder Hausfläche: keine Räume
        return out

    @app.get("/api/floors/{floor_id}/rooms")
    def get_rooms(floor_id: str) -> dict:
        """Räume des Stockwerks aus den Wänden, mit Namen (eigene, aus HA oder „Raum N“), Fläche und Umriss."""
        project = store.load()
        floor = get_floor(project, floor_id)
        if not floor.scale:
            raise HTTPException(409, "Für Räume braucht das Stockwerk einen Maßstab.")
        try:
            res = rooms_io.compute(floor, room_areas(project))
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {"door_m": rooms_io.DOOR_M, "rooms": rooms_io.public(res)}

    @app.put("/api/floors/{floor_id}/room-labels")
    def put_room_labels(floor_id: str, req: RoomLabelSet) -> dict:
        """Eigene Namen der Räume: alle Namensschilder des Stockwerks auf einmal (leer = Namen wieder automatisch)."""
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            floor.room_labels = req.labels
            floor.updated = now()
        return get_rooms(floor_id)

    @app.get("/api/devices/catalog")
    def device_catalog() -> dict:
        """Geräte aus dem letzten Messlauf, mit Namen und Bereichen aus Home Assistant."""
        m = catalog_io.latest_measurement(store.root.parent / "messungen")
        if m is None:
            return {"measured_at": None, "devices": []}
        return {"measured_at": m.get("timestamp"), "devices": catalog_io.build_catalog(m, catalog_io.ha_names())}

    @app.put("/api/floors/{floor_id}/devices", response_model=Floor)
    def put_devices(floor_id: str, devices: list[Placement]) -> Floor:
        keys = [d.key for d in devices]
        if len(keys) != len(set(keys)) or len({d.id for d in devices}) != len(devices):
            raise HTTPException(400, "Ein Gerät ist doppelt platziert")
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            # zugeordnete Netze verwaltet die Ansicht „Messen“ (PUT /api/devices/{key}/bssids): nicht überschreiben
            known = {d.key: d.bssids for d in floor.devices}
            for d in devices:
                if d.key in known:
                    d.bssids = known[d.key]
            for other in project.floors:
                if other.id == floor_id:
                    continue
                clash = sorted({d.key for d in other.devices} & set(keys))
                if clash:
                    label = next(d.label for d in devices if d.key == clash[0])
                    raise HTTPException(409, f"„{label}“ ist schon im Stockwerk „{other.name}“ platziert")
            floor.devices = devices
            floor.updated = now()
        return floor

    # Das Modell gilt für das ganze Haus: einmal je Projektstand und Messlauf eichen, die Karten
    # der Stockwerke bei Bedarf dazu rechnen. Die Sperre verhindert doppeltes Rechnen.
    eval_state: dict = {}
    eval_lock = threading.Lock()

    def evaluation_state() -> dict:
        project = store.load()
        m = catalog_io.latest_measurement(store.root.parent / "messungen")
        # Projektstand als Prüfsumme: Änderungszeiten haben nur Sekundengenauigkeit
        key = (hashlib.sha1(project.model_dump_json().encode()).hexdigest(), (m or {}).get("timestamp"))
        if eval_state.get("key") != key:
            try:
                base = evaluate_io.evaluate_building(project, m)
            except ValueError as e:
                raise HTTPException(409, str(e)) from e
            eval_state.clear()
            eval_state.update(key=key, project=project, m=m, base=base, floors={})
        return eval_state

    def evaluation_for(floor_id: str) -> dict:
        with eval_lock:
            st = evaluation_state()
            floor = get_floor(st["project"], floor_id)
            if floor_id not in st["floors"]:
                try:
                    st["floors"][floor_id] = evaluate_io.evaluate_floor(st["project"], floor, st["m"], st["base"])
                except ValueError as e:
                    raise HTTPException(409, str(e)) from e
            return st["floors"][floor_id]

    @app.get("/api/evaluation")
    def evaluation_overview() -> dict:
        """Haus im Überblick: geeichtes Modell und Abdeckung je Stockwerk."""
        with eval_lock:
            st = evaluation_state()
        floors = []
        for f in sorted(st["project"].floors, key=lambda f: (f.level, f.name)):
            item = {"id": f.id, "name": f.name, "level": f.level}
            try:
                ev = evaluation_for(f.id)
                item.update(coverage=ev["coverage"], shares=ev["shares"], coverage5=ev["coverage5"], shares5=ev["shares5"])
            except HTTPException as e:
                item["error"] = e.detail
            floors.append(item)
        base = st["base"]
        model = evaluate_io.public_model(base["model"])
        model.pop("samples")
        return {"measured_at": base["measured_at"], "model": model, "findings": base["findings"], "floors": floors}

    sim_lock = threading.Lock()

    def scene() -> simulate_io.Scene:
        """Simulationsgrundlage: Auswertung aller Stockwerke, einmal je Projektstand."""
        with eval_lock:
            st = evaluation_state()
        evals = {}
        for f in st["project"].floors:
            try:
                evals[f.id] = evaluation_for(f.id)
            except HTTPException:
                pass   # ohne Maßstab, Wände oder Geräte: nicht Teil der Simulation
        if st.get("scene") is None:
            st["scene"] = simulate_io.Scene(st["base"], evals)
        return st["scene"]

    @app.post("/api/simulation")
    def simulation(req: SimulationRequest) -> dict:
        """Aufstellung durchrechnen: Abdeckung je Stockwerk vorher/nachher, Geräte, Karte eines Stockwerks."""
        with sim_lock:
            return scene().simulate(req)

    @app.post("/api/simulation/recommend")
    def recommend(req: RecommendRequest) -> dict:
        """Bessere Plätze für die gewählten Zugangspunkte (und auf Wunsch neue Repeater) vorschlagen."""
        with sim_lock:
            sc = scene()
            if not sc.aps:
                raise HTTPException(409, "Es ist noch kein Zugangspunkt platziert.")
            return sc.recommend(req.movable, req.add)

    # --- Gerät suchen (Entscheidung 0009) ---------------------------------------------------
    locate_state: dict = {"snap": None, "at": 0.0, "source": None, "error": None}
    locate_lock = threading.Lock()

    def locate_snapshot(refresh: bool, max_age: float = LOCATE_MAX_AGE_S) -> dict:
        """Mesh-Liste der FRITZ!Box (höchstens max_age Sekunden alt); ohne Zugang der letzte Messlauf."""
        from .collect import snapshot

        with locate_lock:
            st = locate_state
            if refresh or st["snap"] is None or time.time() - st["at"] > max_age:
                try:
                    if store.load().demo:   # Beispielhaus: Geräte aus seinem Messlauf, keine echte FRITZ!Box
                        st.update(snap=catalog_io.latest_measurement(store.root.parent / "messungen"), source="beispiel",
                                  error=None)
                    else:
                        st.update(snap=snapshot(), source="live", error=None)
                except (OSError, RuntimeError, KeyError, ValueError, SyntaxError) as e:  # kein Zugang, nicht erreichbar …
                    m = catalog_io.latest_measurement(store.root.parent / "messungen")
                    st.update(snap=m, source="messlauf" if m else None, error=str(e))
                st["at"] = time.time()
            if st["snap"] is None:
                raise HTTPException(409, f"Keine Werte: FRITZ!Box nicht erreichbar ({st['error']}) und noch kein Messlauf.")
            return st

    def locate_with(reading: dict, report: dict | None = None) -> tuple[dict, dict, list[Floor], dict]:
        """Suche mit dem Wert der FRITZ!Box, mit report (Meldung „findbar“) über den eigenen Scan des Handys."""
        with eval_lock:
            st = evaluation_state()
        floors = [f for f in st["project"].floors if f.scale]
        evals = {}
        for f in floors:
            try:
                evals[f.id] = evaluation_for(f.id)
            except HTTPException:
                pass   # ohne Wände oder Geräte: dort wird nicht gesucht
        try:
            if report is not None:
                res = locate_io.locate_scan(st["base"], evals, floors, report, reading)
            else:
                res = locate_io.locate(st["base"], evals, floors, reading)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        locate_io.add_rooms(res, floor_rooms(st["project"], [f for f in floors if f.id in evals]), floors)
        return res, st, floors, evals

    @app.get("/api/locate/devices")
    def locate_devices(refresh: bool = False) -> dict:
        """WLAN-Geräte mit Zugangspunkt und Signal (Mesh-Liste der FRITZ!Box, etwa 5 s; refresh fragt neu ab)."""
        st = locate_snapshot(refresh)
        devices = locate_io.devices(st["snap"], store.load())
        reports = findable_io.all_reports(data_root)
        for d in devices:
            rep = reports.get(findable_io.mac_of(d["key"]))
            d["findable"] = findable_io.summary(rep) if rep else None
        return {"source": st["source"], "measured_at": st["snap"].get("timestamp"), "error": st["error"], "devices": devices}

    @app.post("/api/locate")
    def locate(req: LocateRequest) -> dict:
        """Wo liegt das Gerät wahrscheinlich? Wahrscheinlichkeit je Stockwerk, Bereich und Karte je Stockwerk.
        Fragt die FRITZ!Box neu ab, wenn die Werte älter als LOCATE_SEARCH_AGE_S sind."""
        st = locate_snapshot(False, LOCATE_SEARCH_AGE_S)
        dev = next((d for d in locate_io.devices(st["snap"], store.load()) if d["key"] == req.device), None)
        if dev is None:
            raise HTTPException(404, "Das Gerät ist gerade nicht im WLAN (laut FRITZ!Box).")
        reading = {"ap": dev["ap"], "band": dev["band"], "rssi": dev["rssi"], "measured_at": st["snap"].get("timestamp")}
        rep = findable_io.load(data_root, findable_io.mac_of(req.device))
        ok, why = findable_io.usable(rep, dev if st["source"] == "live" else None)
        use_scan = ok and req.basis == "auto"
        result, est, _, _ = locate_with(reading, rep if use_scan else None)
        prev = locate_io.last_found(est["project"], req.device)
        previous = ({"t": prev[1].t.isoformat(), "floor": prev[0].name, "unchanged": locate_io.unchanged(prev[1], reading)}
                    if prev else None)
        findable = {**findable_io.summary(rep), "usable": ok, "why": why} if rep else None
        return {"device": dev, "source": st["source"], "previous": previous, "basis": "scan" if use_scan else "fritzbox",
                "findable": findable, **locate_io.public(result)}

    # --- Hintergrundmodus „findbar“ (Entscheidung 0010) ------------------------------------
    hosts: dict[str, tuple[float, dict | None]] = {}

    def identify(request: Request) -> dict:
        """Gerät hinter der IP-Adresse der Anfrage (Host-Liste der FRITZ!Box, 10 min zwischengespeichert)."""
        ip = request.client.host if request.client else ""
        hit = hosts.get(ip)
        if hit is None or time.time() - hit[0] > 600:
            try:
                who = fritz_io.FritzBox.configured().host_by_ip(ip)
            except (OSError, RuntimeError, KeyError, ValueError, SyntaxError) as e:
                raise HTTPException(409, f"Ohne FRITZ!Box lässt sich das Handy nicht zuordnen ({e}).") from e
            hit = hosts[ip] = (time.time(), who)
        if hit[1] is None:
            raise HTTPException(409, f"Die FRITZ!Box kennt kein Gerät mit der Adresse {ip}. Meldet sich das Handy "
                                     "direkt (nicht über Home Assistant) und im WLAN des Hauses?")
        return {**hit[1], "ip": ip}

    def fritz_view(key: str) -> dict | None:
        """Wert der FRITZ!Box für ein Gerät bei der Meldung: Die Suche erkennt daran später, ob das Handy bewegt wurde."""
        try:
            st = locate_snapshot(False, findable_io.FRITZ_AGE_S)
        except HTTPException:
            return None
        if st["source"] != "live":
            return None
        dev = next((d for d in locate_io.devices(st["snap"], store.load()) if d["key"] == key), None)
        return {"ap": dev["ap"], "band": dev["band"], "rssi": dev["rssi"], "t": st["snap"].get("timestamp")} if dev else None

    @app.post("/api/findable/report")
    def findable_report(req: FindableIn, request: Request) -> dict:
        """Meldung der Android-App: Scan des ruhenden Handys. Gespeichert wird nur die letzte je Gerät."""
        who = identify(request)
        rep = findable_io.build(req, survey_cells(), who["mac"], who["name"])
        rep["fritz"] = fritz_view(f"client:{rep['mac']}")
        findable_io.save(data_root, rep)
        return {"device": f"client:{rep['mac']}", "name": rep["name"], "n": rep["n"], "t": rep["t"], "ip": who["ip"]}

    @app.delete("/api/findable/report")
    def findable_delete(request: Request) -> dict:
        """Hintergrundmodus ausgeschaltet: die gespeicherte Meldung dieses Handys löschen."""
        who = identify(request)
        return {"deleted": findable_io.delete(data_root, catalog_io.norm_mac(who["mac"]))}

    @app.get("/api/findable")
    def findable_list() -> dict:
        reps = findable_io.all_reports(data_root)
        return {"reports": [{"device": f"client:{mac}", **findable_io.summary(r)} for mac, r in sorted(reps.items())]}

    @app.post("/api/floors/{floor_id}/found")
    def add_found(floor_id: str, req: FoundIn) -> dict:
        """Fundort speichern: geht als Messpunkt in die Eichung ein; dazu, wie gut die Schätzung lag."""
        rep = findable_io.load(data_root, findable_io.mac_of(req.device)) if req.scan_t else None
        rep = rep if rep and rep["t"] == req.scan_t and rep.get("n") else None   # mit diesem Scan wurde gesucht
        result, st, floors, _ = locate_with(req.reading.model_dump(), rep)
        floor = get_floor(st["project"], floor_id)
        if not floor.scale:
            raise HTTPException(409, "Das Stockwerk hat keinen Maßstab.")
        prev = locate_io.last_found(st["project"], req.device)
        if prev and not req.force and locate_io.unchanged(prev[1], req.reading.model_dump()):
            d = locate_io.distance_m(st["base"]["building"], prev[0], prev[1].pos, floor, req.pos)
            if d is None or d > locate_io.MOVED_M:
                raise HTTPException(409, {"code": "unchanged", "message": (
                    f"Die FRITZ!Box meldet noch denselben Wert wie beim letzten Fundort ({prev[1].rssi} dBm, "
                    f"{prev[0].name}). Ruhende Geräte erneuert sie nur alle paar Minuten; wurde das Gerät umgelegt, "
                    "passt der Wert vermutlich noch zum alten Ort. Trotzdem speichern?")})
        quality = locate_io.assess(result, st["base"]["building"], floors, floor, req.pos)
        point = FoundPoint(id=new_id("fd"), pos=req.pos, device=req.device, label=req.label, ap=req.reading.ap,
                           band=req.reading.band, rssi=req.reading.rssi, measured_at=req.reading.measured_at, **quality)
        scan_point = None
        if rep:   # Der Scan stammt von dieser Stelle: vollständiger Messpunkt (alle Zugangspunkte, beide Bänder)
            scan_point = SurveyPoint(id=new_id("s"), pos=req.pos, t=datetime.fromisoformat(rep["t"]), connected=rep["connected"],
                                     aps=rep["aps"], scan_age_s=rep.get("scan_age_s"), device=rep.get("device") or "",
                                     found=point.id)
        with store.edit() as project:
            f = get_floor(project, floor_id)
            f.found.append(point)
            if scan_point:
                f.survey.append(scan_point)
            f.updated = now()
        return {**point.model_dump(mode="json"), "survey_point": scan_point is not None}

    @app.delete("/api/floors/{floor_id}/found/{point_id}")
    def delete_found(floor_id: str, point_id: str) -> dict:
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            keep = [p for p in floor.found if p.id != point_id]
            if len(keep) == len(floor.found):
                raise HTTPException(404, "Fundort nicht gefunden")
            floor.found = keep
            floor.survey = [p for p in floor.survey if p.found != point_id]   # Scan vom Fundort gehört dazu
            floor.updated = now()
        return {"ok": True}

    def survey_cells(project: Project | None = None) -> dict[str, str]:
        """BSSID -> Zugangspunkt: aus dem letzten Messlauf und aus den Zuordnungen eigener Zugangspunkte."""
        m = catalog_io.latest_measurement(store.root.parent / "messungen")
        return {**survey_io.ap_cells(m), **survey_io.placed_cells(project or store.load())}

    @app.get("/api/survey/aps")
    def survey_aps() -> dict:
        """Zugangspunkte mit ihren BSSIDs (Live-Anzeige beim Messen mit dem Handy), auch eigene (manual)."""
        m = catalog_io.latest_measurement(store.root.parent / "messungen")
        project = store.load()
        placed = {d.key: (d, f.name) for f in project.floors for d in f.devices if d.kind == "ap"}
        out = []
        for ap in (m or {}).get("access_points", []):
            key = f"ap:{catalog_io.norm_mac(ap.get('mac'))}"
            d, floor = placed.get(key, (None, None))
            out.append({"key": key, "label": d.label if d else ap.get("name") or key, "floor": floor, "manual": False,
                        "bssids": sorted(c for c, k in survey_io.ap_cells({"access_points": [ap]}).items() if k == key)})
        for key, (d, floor) in placed.items():
            if evaluate_io.is_manual(key):
                out.append({"key": key, "label": d.label, "floor": floor, "manual": True, "bssids": sorted(d.bssids)})
        return {"aps": out, "measured_at": (m or {}).get("timestamp")}

    @app.put("/api/devices/{key}/bssids")
    def put_bssids(key: str, req: BssidSet) -> dict:
        """Netze (BSSIDs aus dem Scan des Handys) einem eigenen Zugangspunkt zuordnen. Ein Netz gehört zu genau
        einem Zugangspunkt: Bei anderen wird es entfernt."""
        if not evaluate_io.is_manual(key):
            raise HTTPException(400, "Netze lassen sich nur eigenen Zugangspunkten zuordnen; die der FRITZ!Box stehen im Messlauf.")
        bssids = sorted({b for b in (catalog_io.norm_mac(x) for x in req.bssids) if len(b) == 12 and b != "020000000000"})
        with store.edit() as project:
            target = next((d for f in project.floors for d in f.devices if d.key == key), None)
            if target is None or target.kind != "ap":
                raise HTTPException(404, "Zugangspunkt nicht gefunden")
            for f in project.floors:
                for d in f.devices:
                    if d.key != key and d.bssids:
                        d.bssids = [b for b in d.bssids if b not in bssids]
            target.bssids = bssids
        return {"key": key, "bssids": bssids}

    @app.post("/api/floors/{floor_id}/survey", response_model=SurveyPoint)
    def add_survey_point(floor_id: str, req: SurveyIn) -> SurveyPoint:
        """Messpunkt aus der Android-App: Signal des verbundenen Zugangspunkts und WLAN-Scan."""
        if store.load().demo:
            raise HTTPException(409, "Im Beispielhaus misst man nicht. Erst das Beispiel beenden (Ansicht „Start“).")
        point = survey_io.make_point(new_id("s"), req, survey_cells())
        if not point.aps and not point.connected:
            raise HTTPException(422, "Der Messpunkt enthält keine WLAN-Werte.")
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            floor.survey.append(point)
            floor.updated = now()
        return point

    @app.delete("/api/floors/{floor_id}/survey/{point_id}")
    def delete_survey_point(floor_id: str, point_id: str) -> dict:
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            keep = [p for p in floor.survey if p.id != point_id]
            if len(keep) == len(floor.survey):
                raise HTTPException(404, "Messpunkt nicht gefunden")
            floor.survey = keep
            floor.updated = now()
        return {"ok": True}

    @app.get("/app/wifi-survey.apk")
    def android_app() -> FileResponse:
        """Android-App zum Messen mit dem Handy (gebaut mit scripts/android_build.sh)."""
        path = store.root.parent / "app" / "wifi-survey.apk"
        if not path.exists() and os.environ.get("WIFI_SURVEY_APK"):
            path = Path(os.environ["WIFI_SURVEY_APK"])      # in der HA-App: Teil des Abbilds
        if not path.exists():
            raise HTTPException(404, "Die Android-App ist noch nicht gebaut.")
        return FileResponse(path, media_type="application/vnd.android.package-archive", filename="wifi-survey.apk",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/api/floors/{floor_id}/evaluation")
    def evaluation(floor_id: str) -> dict:
        """Messwerte je Gerät, Modell, Abdeckung und Hinweise für ein Stockwerk."""
        ev = evaluation_for(floor_id)
        return {**{k: v for k, v in ev.items() if not k.startswith("_")}, "maps": sorted(ev["_maps"]),
                "maps5": sorted(ev["_maps5"])}

    @app.get("/api/floors/{floor_id}/evaluation/heatmap.png")
    def evaluation_heatmap(floor_id: str, ap: str = "best", band: str = "2.4") -> Response:
        ev = evaluation_for(floor_id)
        maps = ev["_maps5"] if band == "5" else ev["_maps"]
        if ap not in maps:
            raise HTTPException(404, "Für diesen Zugangspunkt gibt es keine Karte")
        return Response(evaluate_io.heatmap_png(maps[ap]), media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.post("/api/measurements")
    def measure(scan: bool = True) -> dict:
        """Neuer Messlauf (FRITZ!Box-Mesh plus WLAN-Status und -Scans der Shellys, ca. 1 Minute)."""
        from .collect import run, save

        if store.load().demo:
            raise HTTPException(409, "Im Beispielhaus gibt es keinen echten Messlauf. Erst das Beispiel beenden (Ansicht „Start“).")
        try:
            result = run(scan=scan)
        except Exception as e:  # Zugangsdaten fehlen, FRITZ!Box nicht erreichbar …
            raise HTTPException(502, f"Messlauf fehlgeschlagen: {e}") from e
        save(result, store.root.parent / "messungen")
        return {"timestamp": result["timestamp"], "shellys": len(result["shellys"]),
                "scanned": sum(1 for s in result["shellys"] if s.get("scan")), "clients": len(result["clients"])}

    @app.get("/api/floors/{floor_id}/exterior")
    def exterior(floor_id: str) -> dict:
        """IDs der Wände, die an den Außenraum grenzen (Vorschlag, z. B. zum Setzen des Materials)."""
        floor = get_floor(store.load(), floor_id)
        return {"ids": exterior_walls(floor.walls, floor.image_w, floor.image_h)}

    @app.post("/api/floors/{floor_id}/detect", response_model=DetectResponse)
    def detect_walls(floor_id: str, req: DetectRequest) -> DetectResponse:
        project = store.load()
        floor = get_floor(project, floor_id)
        gray = cv2.imread(str(store.floor_image(floor_id)), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise HTTPException(404, "Bild fehlt")
        result = detect(gray, DetectParams(style=req.style))
        ppm = floor.scale.px_per_m if floor.scale else None
        new_walls = []
        for seg in result.segments:
            t = seg.thickness_px
            if req.snap_thickness and ppm:
                t = snap_thickness_px(t, ppm)
            new_walls.append(Wall(id=new_id("w"), a=seg.a, b=seg.b, thickness_px=round(t, 2),
                                  source="auto", confidence=seg.confidence))
        with store.edit() as project:
            floor = get_floor(project, floor_id)
            before = len(floor.walls)
            if req.mode == "replace_all":
                kept = []
                floor.ignored = []
            elif req.mode == "replace_auto":
                kept = [w for w in floor.walls if w.source != "auto"]
            else:
                kept = list(floor.walls)
            # Vorschläge an Stellen, an denen schon eine bearbeitete Wand liegt, weglassen
            # (sonst entstehen nach Korrekturen doppelte Wände)
            fresh = [w for w in new_walls if covered_share(w, kept + floor.ignored) < 0.5]
            floor.walls = kept + fresh
            floor.updated = now()
        stats = {**result.stats, "hatch_direction": result.hatch_direction, "skipped_covered": len(new_walls) - len(fresh)}
        return DetectResponse(floor=floor, added=len(fresh), removed=before - len(kept), stats=stats)

    @app.middleware("http")
    async def revalidate_app_files(request, call_next):
        # Browser sollen JS/CSS/HTML bei jedem Laden prüfen (304, wenn unverändert),
        # sonst bleiben nach Updates alte Stände im Zwischenspeicher hängen
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def import_plan_file(store: Store, source: Path) -> Plan:
    """Importiert eine Plandatei ohne HTTP (Kommandozeile)."""
    kind = plan_io.kind_for(source.name)
    plan_id = new_id("p")
    target_dir = store.plan_dir(plan_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"original{source.suffix.lower()}"
    shutil.copyfile(source, target)
    pages = plan_io.import_plan(target, target_dir, kind)
    plan = Plan(id=plan_id, name=source.stem, kind=kind, filename=target.name, pages=pages)
    with store.edit() as project:
        project.plans.append(plan)
    return plan


__all__ = ["create_app", "import_plan_file", "snap_thickness_px"]
