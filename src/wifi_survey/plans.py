"""Import von Plänen (PDF oder Bild) und Rendern von Stockwerk-Ausschnitten."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .config import FLOOR_DPI, FLOOR_MAX_PX, PREVIEW_DPI
from .models import Crop, Page

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


class PlanError(Exception):
    pass


def _run(cmd: list[str]) -> str:
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as e:
        raise PlanError(f"Programm fehlt: {cmd[0]} (Paket poppler-utils)") from e
    except subprocess.CalledProcessError as e:
        raise PlanError(f"{cmd[0]} ist fehlgeschlagen: {e.stderr.strip()[:300]}") from e
    return res.stdout


def kind_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    raise PlanError("Nur PDF oder Bilddateien (PNG, JPG, TIFF, BMP, WEBP) werden unterstützt")


def preview_path(plan_dir: Path, index: int) -> Path:
    return plan_dir / f"seite-{index + 1}.png"


def import_plan(source: Path, plan_dir: Path, kind: str) -> list[Page]:
    """Legt Übersichtsbilder je Seite an und gibt die Seiten (in Seitenkoordinaten) zurück."""
    plan_dir.mkdir(parents=True, exist_ok=True)
    if kind == "pdf":
        info = _run(["pdfinfo", str(source)])
        count = next((int(line.split()[-1]) for line in info.splitlines() if line.startswith("Pages:")), 0)
        if count < 1:
            raise PlanError("Das PDF enthält keine Seiten")
        pages = []
        for i in range(count):
            out = preview_path(plan_dir, i)
            _run(["pdftoppm", "-r", str(PREVIEW_DPI), "-f", str(i + 1), "-l", str(i + 1),
                  "-png", "-singlefile", str(source), str(out.with_suffix(""))])
            img = cv2.imread(str(out), cv2.IMREAD_UNCHANGED)
            if img is None:
                raise PlanError(f"Seite {i + 1} ließ sich nicht darstellen")
            h, w = img.shape[:2]
            # bei 72 dpi entspricht 1 px genau 1 pt – Drehung der Seite ist damit schon berücksichtigt
            pages.append(Page(index=i, width=float(w), height=float(h)))
        return pages

    img = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise PlanError("Das Bild ließ sich nicht lesen")
    h, w = img.shape
    out = preview_path(plan_dir, 0)
    if source.suffix.lower() == ".png":
        shutil.copyfile(source, out)
    else:
        cv2.imwrite(str(out), img)
    return [Page(index=0, width=float(w), height=float(h))]


def clamp_crop(crop: Crop, page: Page) -> Crop:
    x = min(max(crop.x, 0.0), page.width - 1)
    y = min(max(crop.y, 0.0), page.height - 1)
    w = min(crop.w, page.width - x)
    h = min(crop.h, page.height - y)
    if w < 10 or h < 10:
        raise PlanError("Der Ausschnitt ist zu klein")
    return Crop(x=round(x, 2), y=round(y, 2), w=round(w, 2), h=round(h, 2))


def render_floor(source: Path, kind: str, page: Page, crop: Crop, out: Path) -> tuple[float, int, int]:
    """Rendert den Ausschnitt als Graustufen-PNG. Gibt (render_scale, Breite, Höhe) zurück."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if kind == "pdf":
        dpi = FLOOR_DPI
        longest = max(crop.w, crop.h) * dpi / 72.0
        if longest > FLOOR_MAX_PX:
            dpi = math.floor(dpi * FLOOR_MAX_PX / longest)
        s = dpi / 72.0
        x, y = round(crop.x * s), round(crop.y * s)
        w, h = round(crop.w * s), round(crop.h * s)
        _run(["pdftoppm", "-r", str(dpi), "-f", str(page.index + 1), "-l", str(page.index + 1),
              "-x", str(x), "-y", str(y), "-W", str(w), "-H", str(h), "-gray",
              "-png", "-singlefile", str(source), str(out.with_suffix(""))])
        img = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise PlanError("Der Ausschnitt ließ sich nicht darstellen")
        return s, img.shape[1], img.shape[0]

    img = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise PlanError("Das Bild ließ sich nicht lesen")
    x0, y0 = round(crop.x), round(crop.y)
    x1, y1 = round(crop.x + crop.w), round(crop.y + crop.h)
    part = np.ascontiguousarray(img[y0:y1, x0:x1])
    s = 1.0
    longest = max(part.shape)
    if longest > FLOOR_MAX_PX:
        s = FLOOR_MAX_PX / longest
        part = cv2.resize(part, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(out), part)
    return s, part.shape[1], part.shape[0]
