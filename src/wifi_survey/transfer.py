"""Projekt exportieren und importieren (ZIP): sichern oder auf einen anderen Server übertragen,
z. B. vom eigenständigen Betrieb in die Home-Assistant-App.

Die Exportdatei enthält das Projekt (Pläne, Stockwerkbilder, `projekt.json`) und die Messläufe.
Beim Import wird das bisherige Projekt nicht gelöscht, sondern nach `sicherungen/` verschoben;
Messläufe werden ergänzt (gleiche Dateinamen = gleicher Zeitpunkt).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .models import Project
from .store import Store

FORMAT = "wifi-survey-export"
FORMAT_VERSION = 1
MANIFEST = "wifi-survey-export.json"
TOP_DIRS = ("projekt", "messungen")
MAX_FILES = 5000
MAX_BYTES = 500 * 1024 * 1024        # entpackt höchstens 500 MB


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")


def _members(data_dir: Path) -> list[tuple[Path, str]]:
    out = []
    for top in TOP_DIRS:
        base = data_dir / top
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if f.is_file() and not f.name.endswith((".tmp", ".bak")):
                out.append((f, f.relative_to(data_dir).as_posix()))
    return out


def export_zip(store: Store, app_version: str) -> Path:
    """Schreibt die Exportdatei in eine temporäre Datei und gibt ihren Pfad zurück."""
    data_dir = store.root.parent
    project = store.load()
    fd, name = tempfile.mkstemp(prefix="wifi-survey-export-", suffix=".zip")
    os.close(fd)
    path = Path(name)
    manifest = {"format": FORMAT, "version": FORMAT_VERSION, "app_version": app_version,
                "created": datetime.now(UTC).isoformat(timespec="seconds"),
                "floors": len(project.floors), "plans": len(project.plans)}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
        # unter der Sperre gelesen, damit Projekt und Bilder zusammenpassen
        with store.locked():
            for f, arc in _members(data_dir):
                # Bilder und PDFs sind schon komprimiert
                kind = zipfile.ZIP_STORED if f.suffix.lower() in (".png", ".pdf", ".jpg", ".jpeg") else zipfile.ZIP_DEFLATED
                zf.write(f, arc, compress_type=kind)
    return path


def _check_names(infos: list[zipfile.ZipInfo]) -> None:
    if len(infos) > MAX_FILES:
        raise ValueError(f"zu viele Dateien ({len(infos)})")
    if sum(i.file_size for i in infos) > MAX_BYTES:
        raise ValueError("entpackt größer als 500 MB")
    for i in infos:
        p = PurePosixPath(i.filename)
        if "\\" in i.filename or p.is_absolute() or ".." in p.parts or len(p.parts) < 2 or p.parts[0] not in TOP_DIRS:
            raise ValueError(f"unerwarteter Eintrag „{i.filename}“")


def import_zip(source: BinaryIO, store: Store) -> dict:
    """Ersetzt das Projekt durch den Inhalt einer Exportdatei und ergänzt die Messläufe."""
    data_dir = store.root.parent
    with zipfile.ZipFile(source) as zf:
        try:
            manifest = json.loads(zf.read(MANIFEST))
        except KeyError:
            raise ValueError("keine Exportdatei von wifi-survey") from None
        if manifest.get("format") != FORMAT:
            raise ValueError("keine Exportdatei von wifi-survey")
        if int(manifest.get("version", 0)) > FORMAT_VERSION:
            raise ValueError("Die Datei stammt aus einer neueren Version; bitte zuerst aktualisieren.")
        infos = [i for i in zf.infolist() if not i.is_dir() and i.filename != MANIFEST]
        _check_names(infos)
        try:
            project = Project.model_validate_json(zf.read("projekt/projekt.json"))
        except KeyError:
            raise ValueError("projekt.json fehlt") from None
        staging = Path(tempfile.mkdtemp(prefix=".import-", dir=data_dir))
        try:
            for i in infos:
                target = staging / i.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(i) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            return _swap(store, staging, project)
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def _swap(store: Store, staging: Path, project: Project) -> dict:
    data_dir = store.root.parent
    backup = None
    with store.locked():
        if store.root.exists() and any(store.root.iterdir()):
            backup = data_dir / "sicherungen" / f"projekt-{_stamp()}"
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(store.root, backup)
        elif store.root.exists():
            store.root.rmdir()
        os.replace(staging / "projekt", store.root)
    added = 0
    meas_dir = data_dir / "messungen"
    for f in sorted((staging / "messungen").glob("*.json")) if (staging / "messungen").exists() else []:
        meas_dir.mkdir(parents=True, exist_ok=True)
        if not (meas_dir / f.name).exists():
            os.replace(f, meas_dir / f.name)
            added += 1
    return {"plans": len(project.plans), "floors": len(project.floors), "measurements_added": added,
            "backup": backup.relative_to(data_dir).as_posix() if backup else None}
