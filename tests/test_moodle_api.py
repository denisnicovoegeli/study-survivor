from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from study_agent.config import MoodleConfig
from study_agent.pipeline.moodle_api import MoodleClient, MoodleError

CFG = MoodleConfig(site_url="https://moodle.test", token="SECRET")
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def client_with(handler):
    return MoodleClient(CFG, http=httpx.Client(transport=httpx.MockTransport(handler)))


def form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def event(i, ts, overdue=False):
    return {"id": i, "name": f"Abgabe {i}", "timesort": ts, "url": f"https://moodle.test/e/{i}",
            "modulename": "assign", "overdue": overdue,
            "course": {"id": 69210, "fullname": "26HS Deep Learning BAI"}}


def test_call_sends_token_and_function_to_rest_endpoint():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen.update(form(request))
        return httpx.Response(200, json={"userid": 1})

    client_with(handler).call("core_webservice_get_site_info")
    assert seen["url"] == "https://moodle.test/webservice/rest/server.php"
    assert seen["wstoken"] == "SECRET"
    assert seen["wsfunction"] == "core_webservice_get_site_info"
    assert seen["moodlewsrestformat"] == "json"


def test_call_rejects_non_allowlisted_function():
    client = client_with(lambda r: pytest.fail("must not send request"))
    with pytest.raises(MoodleError):
        client.call("mod_assign_save_submission")


def test_call_raises_on_moodle_exception():
    def handler(request):
        return httpx.Response(200, json={"exception": "moodle_exception", "errorcode": "invalidtoken",
                                         "message": "Invalid token"})

    with pytest.raises(MoodleError) as exc:
        client_with(handler).call("core_webservice_get_site_info")
    assert exc.value.errorcode == "invalidtoken"
    assert "SECRET" not in str(exc.value)


def test_upcoming_deadlines_window_mapping_and_sort():
    seen = {}
    later = int((NOW + timedelta(days=3)).timestamp())
    sooner = int((NOW + timedelta(days=1)).timestamp())

    def handler(request):
        seen.update(form(request))
        return httpx.Response(200, json={"events": [event(2, later), event(1, sooner)], "firstid": 1, "lastid": 2})

    result = client_with(handler).upcoming_deadlines(days=14, now=NOW)
    assert int(seen["timesortfrom"]) == int((NOW - timedelta(days=7)).timestamp())
    assert int(seen["timesortto"]) == int((NOW + timedelta(days=14)).timestamp())
    assert [d.name for d in result] == ["Abgabe 1", "Abgabe 2"]
    d = result[0]
    assert (d.course, d.course_id, d.kind, d.url) == ("26HS Deep Learning BAI", 69210, "assign", "https://moodle.test/e/1")
    assert d.due == datetime.fromtimestamp(sooner, tz=timezone.utc)
    assert d.source == "" and not d.all_day


def test_upcoming_deadlines_paginates():
    calls = []

    def handler(request):
        f = form(request)
        calls.append(f.get("aftereventid"))
        if "aftereventid" not in f:
            events = [event(i, int(NOW.timestamp()) + i) for i in range(1, 51)]
            return httpx.Response(200, json={"events": events, "firstid": 1, "lastid": 50})
        return httpx.Response(200, json={"events": [event(51, int(NOW.timestamp()) + 51)], "firstid": 51, "lastid": 51})

    result = client_with(handler).upcoming_deadlines(days=14, now=NOW)
    assert len(result) == 51
    assert calls == [None, "50"]


def test_course_grades_maps_course_names():
    def handler(request):
        fn = form(request)["wsfunction"]
        if fn == "core_webservice_get_site_info":
            return httpx.Response(200, json={"userid": 7})
        if fn == "core_enrol_get_users_courses":
            assert form(request)["userid"] == "7"
            return httpx.Response(200, json=[{"id": 10, "fullname": "Maschinelles Lernen FS25"}])
        if fn == "gradereport_overview_get_course_grades":
            return httpx.Response(200, json={"grades": [{"courseid": 10, "grade": "5.5"}, {"courseid": 99, "grade": "-"}]})
        raise AssertionError(fn)

    grades = client_with(handler).course_grades()
    assert [(g.course, g.grade) for g in grades] == [("Maschinelles Lernen FS25", "5.5"), ("99", "-")]
