"""Speicherung des Projekts als JSON-Datei (ein Nutzer, ein Prozess)."""

from __future__ import annotations

import json
import os
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import Project


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.file = root / "projekt.json"
        self._lock = threading.RLock()
        root.mkdir(parents=True, exist_ok=True)

    def plan_dir(self, plan_id: str) -> Path:
        return self.root / "plaene" / plan_id

    def floor_image(self, floor_id: str) -> Path:
        return self.root / "stockwerke" / f"{floor_id}.png"

    def load(self) -> Project:
        with self._lock:
            if not self.file.exists():
                return Project()
            return Project.model_validate_json(self.file.read_text())

    def save(self, project: Project) -> None:
        with self._lock:
            data = project.model_dump_json(indent=1)
            tmp = self.file.with_suffix(".json.tmp")
            tmp.write_text(data)
            if self.file.exists():
                os.replace(self.file, self.file.with_suffix(".json.bak"))
            os.replace(tmp, self.file)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Sperre ohne Laden, z. B. um Projektdateien als Ganzes zu lesen oder auszutauschen."""
        with self._lock:
            yield

    @contextmanager
    def edit(self) -> Iterator[Project]:
        """Laden, ändern, speichern – unter Sperre."""
        with self._lock:
            project = self.load()
            yield project
            self.save(project)

    def export(self) -> dict:
        return json.loads(self.load().model_dump_json())
