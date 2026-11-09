"""Routen und Logik fuer den Ordner-Upload mit Pfadschutz und Unterordner-Erhalt (T6).

Regeln:
- Schweizer Rechtschreibung (ss statt sz, keine Geviertstriche).
- Ordner waehlen (webkitdirectory) und per Drag-and-drop (webkitGetAsEntry).
- Unterordner bleiben unter _eigene/<Kurs>/... erhalten.
- Nicht erlaubte Dateitypen (.pdf, .pptx, .docx, .xlsx erlaubt) werden uebersprungen und aufgelistet.
- Gesamtgroessenlimit (50 MB) mit verstaendlicher Fehlermeldung.
- Pfadschutz gegen Path Traversal (keine .., keine absoluten Pfade).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from fastapi import APIRouter, File, Form, HTTPException, UploadFile
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    APIRouter = None
    class HTTPException(Exception):
        def __init__(self, status_code: int = 500, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
    UploadFile = object

from study_agent.pipeline.eigene import EIGENE_EXTENSIONS, MAX_SIZE, save_eigene_file

MAX_BATCH_SIZE = MAX_SIZE  # 50 MB Gesamtgroesse

# Von plugin_api gesetzt (Hermes laedt das Plugin ohne Paket).
data_dir_fn = None
cache_clear_fn = None


def _get_data_dir() -> Path:
    if data_dir_fn is not None:
        return data_dir_fn()
    from study_agent.server.dashboard.plugin_api import data_dir
    return data_dir()


def _clear_cache():
    try:
        if cache_clear_fn is not None:
            cache_clear_fn()
            return
        from study_agent.server.dashboard.plugin_api import cache_clear
        cache_clear()
    except Exception:
        pass


def upload_folder_batch(
    course: str,
    files_with_paths: List[Tuple[str, bytes]],
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Verarbeitet einen Batch von Dateien mit relativen Pfaden fuer einen Kurs.

    - Behaelt Unterordner bei
    - Ueberspringt nicht erlaubte Typen und fuehrt sie in 'skipped' auf
    - Prueft Gesamtgroesse (50 MB)
    - Verhindert Pfadausbrueche (Path Traversal)
    """
    if data_dir is None:
        data_dir = _get_data_dir()

    if not files_with_paths:
        raise ValueError("Keine Dateien zum Hochladen uebergeben.")

    # 1. Gesamtgroesse pruefen
    total_bytes = sum(len(content) for _, content in files_with_paths)
    if total_bytes > MAX_BATCH_SIZE:
        total_mb = total_bytes / (1024 * 1024)
        limit_mb = MAX_BATCH_SIZE / (1024 * 1024)
        raise ValueError(
            f"Gesamtgrösse ({total_mb:.1f} MB) überschreitet das Limit von {limit_mb:.0f} MB."
        )

    saved: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for rel_path, data in files_with_paths:
        p = Path(rel_path)
        name = p.name
        suffix = p.suffix.lower()

        # 2. Endung pruefen
        if suffix not in EIGENE_EXTENSIONS:
            skipped.append({
                "path": rel_path,
                "name": name,
                "reason": f"Dateityp {suffix or 'ohne Endung'} nicht erlaubt (nur {', '.join(sorted(EIGENE_EXTENSIONS))})",
            })
            continue

        # 3. Unterordner extrahieren
        subparts = [part for part in p.parts[:-1] if part and part not in (".", "")]
        subpath = "/".join(subparts) if subparts else None

        # 4. Datei mit Pfadschutz speichern
        try:
            dest = save_eigene_file(
                data_dir=data_dir,
                course=course,
                filename=name,
                data=data,
                subpath=subpath,
            )
            saved.append({
                "name": name,
                "path": str(dest.relative_to(data_dir)),
                "size": len(data),
            })
        except ValueError as exc:
            # Bei Pfadschutzverletzung oder ungueltigem Kurs wird sofort abgebrochen
            if "Pfadausbruch" in str(exc) or "Pfadbestandteil" in str(exc) or "Kurs" in str(exc):
                raise
            skipped.append({
                "path": rel_path,
                "name": name,
                "reason": str(exc),
            })

    _clear_cache()

    return {
        "ok": True,
        "saved_count": len(saved),
        "skipped_count": len(skipped),
        "saved": saved,
        "skipped": skipped,
        "total_bytes": total_bytes,
    }


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

if HAS_FASTAPI:
    router = APIRouter(prefix="/kurse", tags=["upload"])

    @router.post("/upload-folder")
    async def post_upload_folder(
        course: str = Form(...),
        files: List[UploadFile] = File(...),
        paths: Optional[List[str]] = Form(None),
    ):
        files_with_paths: List[Tuple[str, bytes]] = []

        for idx, file in enumerate(files):
            content = await file.read()
            # Falls relative Pfade vom Client uebergeben wurden, diese nutzen
            rel = (paths[idx] if paths and idx < len(paths) else "") or file.filename or "datei"
            files_with_paths.append((rel, content))

        try:
            result = upload_folder_batch(course=course, files_with_paths=files_with_paths)
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
else:
    router = None
