from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from study_agent.config import MoodleConfig

ALLOWED_FUNCTIONS = frozenset({
    "core_webservice_get_site_info",
    "core_enrol_get_users_courses",
    "core_calendar_get_action_events_by_timesort",
    "gradereport_overview_get_course_grades",
})

PAGE_SIZE = 50
MAX_PAGES = 10
OVERDUE_LOOKBACK = timedelta(days=7)


class MoodleError(RuntimeError):
    def __init__(self, message: str, errorcode: str = ""):
        super().__init__(message)
        self.errorcode = errorcode


@dataclass(frozen=True)
class Deadline:
    course: str
    name: str
    due: datetime
    url: str
    kind: str
    overdue: bool
    source: str = ""  # leer = Moodle-Kalender, sonst Quelldatei aus termine/*.yaml
    all_day: bool = False  # nur Datum bekannt; due ist dann 23:59 Zürich
    course_id: int = 0


@dataclass(frozen=True)
class CourseGrade:
    course: str
    grade: str


class MoodleClient:
    def __init__(self, config: MoodleConfig, http: httpx.Client | None = None):
        self._config = config
        self._http = http or httpx.Client(timeout=30)

    def call(self, function: str, **params) -> dict | list:
        if function not in ALLOWED_FUNCTIONS:
            raise MoodleError(f"{function} ist nicht freigegeben (nur lesende Funktionen)", "notallowed")
        data = {"wstoken": self._config.token, "wsfunction": function, "moodlewsrestformat": "json", **params}
        try:
            response = self._http.post(self._config.base_url, data=data)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MoodleError(f"{function}: {type(exc).__name__}", "network") from None
        payload = response.json()
        if isinstance(payload, dict) and "exception" in payload:
            code = payload.get("errorcode", "unknown")
            raise MoodleError(f"{function}: {code}: {payload.get('message', '')}", code)
        return payload

    def upcoming_deadlines(self, days: int, now: datetime | None = None) -> list[Deadline]:
        now = now or datetime.now(timezone.utc)
        params = {
            "timesortfrom": int((now - OVERDUE_LOOKBACK).timestamp()),
            "timesortto": int((now + timedelta(days=days)).timestamp()),
            "limitnum": PAGE_SIZE,
        }
        events: list[dict] = []
        for _ in range(MAX_PAGES):
            page = self.call("core_calendar_get_action_events_by_timesort", **params)
            events.extend(page.get("events", []))
            if len(page.get("events", [])) < PAGE_SIZE:
                break
            params["aftereventid"] = page["lastid"]
        deadlines = [
            Deadline(
                course=(e.get("course") or {}).get("fullname", ""),
                name=e["name"],
                due=datetime.fromtimestamp(e["timesort"], tz=timezone.utc),
                url=e.get("url") or e.get("viewurl") or "",
                kind=e.get("modulename") or e.get("eventtype") or "",
                overdue=bool(e.get("overdue")),
                course_id=int((e.get("course") or {}).get("id") or 0),
            )
            for e in events
        ]
        return sorted(deadlines, key=lambda d: d.due)

    def course_grades(self) -> list[CourseGrade]:
        userid = self.call("core_webservice_get_site_info")["userid"]
        names = {c["id"]: c["fullname"] for c in self.call("core_enrol_get_users_courses", userid=userid)}
        grades = self.call("gradereport_overview_get_course_grades").get("grades", [])
        return [CourseGrade(course=names.get(g["courseid"], str(g["courseid"])), grade=str(g.get("grade", "-")))
                for g in grades]
