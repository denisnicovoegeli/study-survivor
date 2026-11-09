"""Explorer-Routen und Datenaufbereitung fuer das Studium-Dashboard (T2).

Bietet bereinigte Moodle-Struktur, Link-Parser (.desktop, .webloc),
Artefakt-Verknuepfungen (Zusammenfassung, Cheatsheet, Folien) und
Verarbeitungsstand (neu/veraltet aus study pending).
"""

import html
import os
import plistlib
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_TAG_RE = re.compile(r"[<＜][^>＞]+[>＞]")
_SECRET_PARAM = re.compile(r"token|key|secret|sig|auth|code|password|invite", re.I)


def clean_section_title(raw: str) -> str:
    """Bereinigt HTML-Tags (auch Vollbreiten-Zeichen von moodle-dl) aus Abschnittsnamen.

    Beispiel:
        ＜span class=＂course-mod_subsection＂＞2 Context, Transformer＜⧸span＞
        -> 2 Context, Transformer
    """
    if not raw or not isinstance(raw, str):
        return ""
    cleaned = _TAG_RE.sub("", raw)
    cleaned = html.unescape(cleaned)
    return " ".join(cleaned.split())


def strip_week_prefix(title: str, week_num: int) -> str:
    """Vermeidet doppelte Präfixe wie 'W01 Woche 1:' wenn week_label W01 angezeigt wird.

    Beispiele:
        "Woche 1: Organisatorisches" -> "Organisatorisches"
        "W01 Woche 1: Organisatorisches" -> "Organisatorisches"
        "Woche 1： Organisatorisches" -> "Organisatorisches"
        "W1 - Einführung" -> "Einführung"
        "Woche 1" -> "Woche 1"
    """
    if not title:
        return ""
    # Entferne vorangestellte Muster wie W01, W1, Woche 1, Woche 01 gefolgt von Trennzeichen
    cleaned = re.sub(r"^(?:W(?:oche)?\s*0?\d+\b\s*[:：.\-–—]?\s*)+", "", title, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else title


def load_moodle_section_order(db_path: Optional[Path], course_name: str) -> Dict[str, Dict[str, Any]]:
    """Liest section_id und Aktualisierungszeit pro Abschnitt aus moodle_state.db (nur lesend)."""
    if not db_path or not Path(db_path).is_file():
        return {}
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
        cur = con.cursor()
        rows = cur.execute(
            "SELECT saved_to, section_id, content_timemodified FROM files WHERE saved_to IS NOT NULL AND (course_fullname = ? OR saved_to LIKE ?)",
            (course_name, f"%/{course_name}/%")
        ).fetchall()
        con.close()
        result: Dict[str, Dict[str, Any]] = {}
        for saved_to, sec_id, timemod in rows:
            if not saved_to:
                continue
            parts = Path(saved_to).parts
            if course_name in parts:
                idx = parts.index(course_name)
                if idx + 1 < len(parts):
                    sec_folder = parts[idx + 1]
                else:
                    sec_folder = parts[-2] if len(parts) >= 2 else ""
            elif len(parts) >= 2:
                sec_folder = parts[-2]
            else:
                sec_folder = ""
            if not sec_folder:
                continue
            t_mod = float(timemod) if timemod else 0.0
            if sec_folder not in result:
                result[sec_folder] = {"section_id": sec_id, "last_modified": t_mod}
            else:
                if sec_id is not None and (result[sec_folder]["section_id"] is None or sec_id < result[sec_folder]["section_id"]):
                    result[sec_folder]["section_id"] = sec_id
                if t_mod > result[sec_folder]["last_modified"]:
                    result[sec_folder]["last_modified"] = t_mod
        return result
    except Exception:
        return {}


def redact_url(url: str) -> str:
    """Entfernt sensible Parameter aus URLs."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        params = parse_qsl(parts.query, keep_blank_values=True)
        if any(_SECRET_PARAM.search(k) for k, _ in params):
            # Bereinige sensible Parameter
            safe_params = [(k, v) for k, v in params if not _SECRET_PARAM.search(k)]
            query_str = "&".join(f"{k}={v}" for k, v in safe_params)
            return urlunsplit(parts._replace(query=query_str, fragment=""))
    except Exception:
        pass
    return url


def parse_link_file(path: Path) -> Optional[Dict[str, str]]:
    """Liest .desktop (Linux/Pi) oder .webloc (macOS) und extrahiert Ziel-URL und Name."""
    if not path.is_file():
        return None

    suffix = path.suffix.lower()

    if suffix == ".desktop":
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        url_m = re.search(r"^URL\s*=\s*(.+)$", text, re.MULTILINE)
        if not url_m:
            return None
        url = url_m.group(1).strip()

        name_m = re.search(r"^Name\s*=\s*(.+)$", text, re.MULTILINE)
        if name_m:
            raw_name = name_m.group(1).strip()
            if raw_name.startswith("/"):
                # Absolute Pfade aus moodle-dl auf den letzten Pfadteil kuerzen
                last_part = raw_name.rstrip("/").split("/")[-1].strip()
                name = last_part if last_part else path.stem
            else:
                name = raw_name if raw_name else path.stem
        else:
            name = path.stem

        return {
            "name": name,
            "url": redact_url(url),
            "kind": "url",
        }

    if suffix == ".webloc":
        try:
            data = plistlib.loads(path.read_bytes())
            if isinstance(data, dict):
                url = data.get("URL")
                if url:
                    return {
                        "name": path.stem,
                        "url": redact_url(str(url).strip()),
                        "kind": "url",
                    }
        except Exception:
            # Fallback fuer textbasierte XML-Plists falls plistlib fehlschlaegt
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"<string>([^<]+)</string>", text)
                if m:
                    return {
                        "name": path.stem,
                        "url": redact_url(m.group(1).strip()),
                        "kind": "url",
                    }
            except Exception:
                pass
        return None

    return None


def extract_week_number(name: str) -> int:
    """Ermittelt die Wochennummer aus einem Abschnitts- oder Dateinamen."""
    m = re.search(r"(?:Woche|W)\s*0?(\d+)", name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 999


def current_semester_week(today: Optional[date] = None) -> int:
    """Berechnet die aktuelle Semesterwoche (1-basiert) ab Semesterbeginn."""
    if today is None:
        today = date.today()
    # HS beginnt ca. 15. September, FS ca. 15. Februar
    if today.month >= 8:
        sem_start = date(today.year, 9, 15)
    elif today.month >= 2:
        sem_start = date(today.year, 2, 15)
    else:
        sem_start = date(today.year - 1, 9, 15)

    delta_days = (today - sem_start).days
    if delta_days < 0:
        return 1
    week = (delta_days // 7) + 1
    return min(max(1, week), 16)


def build_course_tree(
    course_name: str,
    moodle_dir: Path,
    lernen_dir: Path,
    knowledge_dir: Path,
    pending_list: Optional[List[Dict[str, Any]]] = None,
    moodle_db: Optional[Path] = None,
) -> Dict[str, Any]:
    """Erstellt den Moodle-basierten Explorer-Baum fuer einen Kurs.

    Schliesst Artefakte (Zusammenfassung, Cheatsheet, Folien) an verarbeitete PDFs an
    und markiert offene Dateien aus pending.
    """
    if pending_list is None:
        pending_list = []

    # Map von relativem Pfad (relativ zu moodle_dir) auf pending-Eintrag
    pending_map = {}
    for p in pending_list:
        rel = p.get("rel")
        if rel:
            pending_map[rel] = p.get("reason", "neu")

    course_moodle = moodle_dir / course_name
    course_lernen = lernen_dir / course_name
    course_knowledge = knowledge_dir / course_name
    eigene_moodle = moodle_dir / "_eigene" / course_name

    cur_week = current_semester_week()
    sections = []
    direct_files = []

    if course_moodle.is_dir():
        # Abschnitte und direkte Dateien durchgehen
        try:
            entries = sorted(course_moodle.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            entries = []

        for entry in entries:
            if entry.name.startswith(".") or entry.name in {"__pycache__"}:
                continue

            if entry.is_dir():
                sec_raw_name = entry.name
                sec_clean_name = clean_section_title(sec_raw_name)
                sec_week = extract_week_number(sec_raw_name)
                sec_label = f"W{sec_week:02d}" if sec_week < 999 else ""
                sec_display_name = strip_week_prefix(sec_clean_name, sec_week) if sec_label else sec_clean_name

                sec_lernen = course_lernen / sec_raw_name
                sec_knowledge = course_knowledge / sec_raw_name

                files = []
                sec_latest_mtime = 0.0
                try:
                    sec_files = sorted(entry.iterdir(), key=lambda p: p.name.lower())
                except OSError:
                    sec_files = []

                for f in sec_files:
                    if f.name.startswith(".") or not f.is_file():
                        continue

                    try:
                        st = f.stat()
                        f_mtime = st.st_mtime
                        f_size = st.st_size
                    except OSError:
                        f_mtime = 0.0
                        f_size = 0

                    if f_mtime > sec_latest_mtime:
                        sec_latest_mtime = f_mtime

                    lower_name = f.name.lower()
                    rel_moodle = f"{course_name}/{sec_raw_name}/{f.name}"
                    file_item: Dict[str, Any] = {
                        "name": f.name,
                        "path": rel_moodle,
                        "root": "moodle",
                        "size": f_size,
                    }

                    if lower_name.endswith(".desktop") or lower_name.endswith(".webloc"):
                        link_info = parse_link_file(f)
                        if link_info:
                            file_item.update(link_info)
                            files.append(file_item)
                            continue

                    if lower_name.endswith(".pdf"):
                        file_item["kind"] = "pdf"
                        base_stem = f.name[:-4]

                        # Pruefe Artefakte in lernen und knowledge
                        zf_name = f"{base_stem}.zusammenfassung.md"
                        zf_path = sec_lernen / zf_name
                        if zf_path.is_file():
                            file_item["has_zusammenfassung"] = True
                            file_item["zusammenfassung_path"] = f"{course_name}/{sec_raw_name}/{zf_name}"

                        cs_name = f"{base_stem}.cheatsheet.md"
                        cs_path = sec_lernen / cs_name
                        if cs_path.is_file():
                            file_item["has_cheatsheet"] = True
                            file_item["cheatsheet_path"] = f"{course_name}/{sec_raw_name}/{cs_name}"

                        fl_name = f"{f.name}.folien.md"
                        fl_path = sec_knowledge / fl_name
                        if fl_path.is_file():
                            file_item["has_folien"] = True
                            file_item["folien_path"] = f"{course_name}/{sec_raw_name}/{fl_name}"

                        # Pending-Status
                        if rel_moodle in pending_map:
                            file_item["pending"] = pending_map[rel_moodle]

                        files.append(file_item)
                    elif lower_name.endswith((".md", ".txt", ".py", ".sql")):
                        file_item["kind"] = "markdown" if lower_name.endswith(".md") else "text"
                        files.append(file_item)
                    elif lower_name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
                        file_item["kind"] = "image"
                        files.append(file_item)
                    else:
                        file_item["kind"] = "other"
                        files.append(file_item)

                if files:
                    sections.append({
                        "name": sec_raw_name,
                        "clean_name": sec_clean_name,
                        "display_name": sec_display_name,
                        "week_num": sec_week,
                        "week_label": sec_label,
                        "last_modified": sec_latest_mtime,
                        "is_current": False,
                        "files": files,
                    })

            elif entry.is_file():
                # Datei direkt auf Kursebene
                lower_name = entry.name.lower()
                rel_moodle = f"{course_name}/{entry.name}"
                try:
                    f_size = entry.stat().st_size
                except OSError:
                    f_size = 0
                item: Dict[str, Any] = {
                    "name": entry.name,
                    "path": rel_moodle,
                    "root": "moodle",
                    "size": f_size,
                }
                if lower_name.endswith(".desktop") or lower_name.endswith(".webloc"):
                    link_info = parse_link_file(entry)
                    if link_info:
                        item.update(link_info)
                        direct_files.append(item)
                else:
                    item["kind"] = "pdf" if lower_name.endswith(".pdf") else "other"
                    direct_files.append(item)

    # Abschnitte in Moodle-Reihenfolge (aus moodle_state.db) sortieren
    db_order = load_moodle_section_order(moodle_db, course_name)
    for sec in sections:
        sec_name = sec["name"]
        if sec_name in db_order:
            info = db_order[sec_name]
            sec["section_id"] = info["section_id"] if info["section_id"] is not None else 999999999
            if info.get("last_modified"):
                sec["last_modified"] = info["last_modified"]
        else:
            sec["section_id"] = 999999999

    # Sortierung: zuerst nach Moodle section_id, dann nach week_num, dann nach Name
    sections.sort(key=lambda s: (s["section_id"], s["week_num"], s["clean_name"]))

    # Nur die aktuelle Woche ist standardmaessig aufgeklappt;
    # gibt es keine eindeutige aktuelle Woche, ist der zuletzt geaenderte Abschnitt offen.
    matching_current = [s for s in sections if s["week_num"] == cur_week and s["week_num"] < 999]
    if len(matching_current) == 1:
        target_name = matching_current[0]["name"]
    elif sections:
        target_name = max(sections, key=lambda s: s.get("last_modified", 0.0))["name"]
    else:
        target_name = None

    for s in sections:
        s["is_current"] = (s["name"] == target_name)

    # Eigene Uploads fuer diesen Kurs (_eigene/<Kurs>/...)
    eigene_files = []
    if eigene_moodle.is_dir():
        try:
            for root, _, fs in os.walk(eigene_moodle):
                for f in sorted(fs):
                    if f.startswith("."):
                        continue
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(moodle_dir).as_posix()
                    lower_f = f.lower()
                    kind = "pdf" if lower_f.endswith(".pdf") else "markdown" if lower_f.endswith(".md") else "other"
                    eigene_files.append({
                        "name": f,
                        "path": rel_p,
                        "root": "moodle",
                        "kind": kind,
                        "size": full_p.stat().st_size,
                        "is_eigene": True,
                    })
        except OSError:
            pass

    return {
        "course": course_name,
        "current_week": cur_week,
        "sections": sections,
        "direct_files": direct_files,
        "eigene": eigene_files,
    }


def register_routes(router: Any, get_settings_fn: Any, cached_study_fn: Any) -> None:
    """Registriert Explorer-Routen am FastAPI-Router."""
    from fastapi import Query

    @router.get("/explorer/tree")
    async def get_explorer_tree(course: str = Query(..., description="Name des Kurses")):
        settings = get_settings_fn()
        pending_data = cached_study_fn("pending", "--json")
        pending_list = pending_data if isinstance(pending_data, list) else []

        moodle_dir = settings.data_dir
        lernen_dir = settings.lernen_dir
        knowledge_dir = settings.knowledge_dir
        moodle_db = getattr(settings, "moodle_db", None) or (moodle_dir / "moodle_state.db")

        return build_course_tree(
            course_name=course,
            moodle_dir=moodle_dir,
            lernen_dir=lernen_dir,
            knowledge_dir=knowledge_dir,
            pending_list=pending_list,
            moodle_db=moodle_db,
        )
