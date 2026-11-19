import datetime as dt
import json

import pytest
from django.test import Client

from api.models import ApiToken, AuditLog
from issues.models import Issue
from meetings.models import Headline, Meeting, MeetingRating
from rocks.models import Rock, RockUpdate
from scorecard.models import Measurable, ScoreEntry
from todos.models import Todo


@pytest.fixture
def token(member):
    return ApiToken.issue(member, "Claude")


def call(raw, method, path, body=None):
    c = Client()
    kwargs = {"HTTP_AUTHORIZATION": f"Bearer {raw}"} if raw else {}
    if body is not None:
        kwargs.update(data=json.dumps(body), content_type="application/json")
    return getattr(c, method.lower())(path, **kwargs)


def mcp(raw, method, params=None, rid=1):
    msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if rid is not None:
        msg["id"] = rid
    return Client().post("/mcp", data=json.dumps(msg), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {raw}")


def test_token_is_hashed_and_shown_once(member):
    token, raw = ApiToken.issue(member, "Script")
    assert raw.startswith("sneos_")
    assert token.token_hash != raw and raw not in token.token_hash
    assert ApiToken.find(raw) == token
    assert ApiToken.find(raw + "x") is None


def test_rest_requires_a_live_token(token, quarter):
    _, raw = token
    assert call(None, "GET", "/api/v1/me").status_code == 401
    assert call("sneos_nope", "GET", "/api/v1/me").status_code == 401
    assert call(raw, "GET", "/api/v1/me").json()["email"] == "kim@steuartnutrition.com"
    t = token[0]
    t.revoked_at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    t.save()
    assert call(raw, "GET", "/api/v1/me").status_code == 401


def test_rest_index_lists_endpoints(token):
    data = call(token[1], "GET", "/api/v1/").json()
    assert "GET /api/v1/rocks" in data["endpoints"]


def test_measurable_value_write_respects_ownership(token, member, other, teams, quarter):
    _, raw = token
    mine = Measurable.objects.create(team=teams["ky"], title="Tons shipped", owner=member, goal=100)
    theirs = Measurable.objects.create(team=teams["lr"], title="LR tons", owner=other)
    r = call(raw, "POST", f"/api/v1/measurables/{mine.pk}/values", {"week": "2026-10-08", "value": "120"})
    assert r.status_code == 200 and r.json()["on_goal"] is True
    entry = ScoreEntry.objects.get(measurable=mine)
    assert entry.week_start == dt.date(2026, 10, 5) and entry.updated_by == member
    assert call(raw, "POST", f"/api/v1/measurables/{theirs.pk}/values", {"week": "2026-10-08", "value": 5}).status_code == 403
    log = AuditLog.objects.filter(is_write=True).order_by("id")
    assert [(entry.ok, entry.status) for entry in log] == [(True, 200), (False, 403)]
    assert log[0].user == member and log[0].object_type == "measurable" and log[0].payload["value"] == "120"


def test_scorecard_read(token, member, teams, quarter):
    m = Measurable.objects.create(team=teams["ky"], title="Calls", owner=member, goal=10)
    ScoreEntry.objects.create(measurable=m, week_start=quarter.weeks()[0], value=12)
    data = call(token[1], "GET", "/api/v1/scorecard?team=kentucky").json()
    assert data["measurables"][0]["weeks"][0] == {"week": quarter.weeks()[0].isoformat(), "value": 12, "on_goal": True}


def test_rock_create_update_and_weekly_status(token, member, teams, quarter):
    _, raw = token
    r = call(raw, "POST", "/api/v1/rocks", {"team": "KY", "title": "Ship new mixer"})
    assert r.status_code == 201
    rock = Rock.objects.get(pk=r.json()["id"])
    assert rock.owner == member and rock.quarter == quarter and rock.team == teams["ky"]

    bad = call(raw, "POST", f"/api/v1/rocks/{rock.pk}/updates", {"rag": "red", "note": "Parts late"})
    assert bad.status_code == 400 and "recovery plan" in bad.json()["error"]
    ok = call(raw, "POST", f"/api/v1/rocks/{rock.pk}/updates", {"rag": "red", "note": "Parts late", "recovery_plan": "Air freight"})
    assert ok.status_code == 200
    rock.refresh_from_db()
    assert rock.status == Rock.OFF_TRACK and RockUpdate.objects.get().author == member

    assert call(raw, "PATCH", f"/api/v1/rocks/{rock.pk}", {"status": "done"}).json()["status"] == "done"
    assert call(raw, "GET", f"/api/v1/rocks/{rock.pk}").json()["updates"][0]["rag"] == "red"


def test_cannot_create_rock_for_another_team(token, teams, quarter):
    assert call(token[1], "POST", "/api/v1/rocks", {"team": "le-roy", "title": "Nope"}).status_code == 403
    assert not Rock.objects.exists()


def test_read_only_token_cannot_write(member, teams, quarter):
    _, raw = ApiToken.issue(member, "Reader", can_write=False)
    assert call(raw, "POST", "/api/v1/issues", {"team": "kentucky", "title": "x"}).status_code == 403
    assert call(raw, "GET", "/api/v1/issues?team=kentucky").status_code == 200
    tools = mcp(raw, "tools/list").json()["result"]["tools"]
    assert all(t["annotations"]["readOnlyHint"] for t in tools)


def test_issue_todo_and_headline_writes(token, member, ky_peer, teams, quarter):
    _, raw = token
    issue = call(raw, "POST", "/api/v1/issues", {"team": "kentucky", "title": "Dryer down"}).json()
    assert call(raw, "PATCH", f"/api/v1/issues/{issue['id']}", {"priority": 1}).json()["priority"] == 1
    solved = call(raw, "PATCH", f"/api/v1/issues/{issue['id']}", {"solve": True, "resolution": "Replaced belt"}).json()
    assert solved["status"] == "solved" and Issue.objects.get().resolution == "Replaced belt"

    todo = call(raw, "POST", "/api/v1/todos", {"team": "kentucky", "title": "Order belts", "owner": "Pat Peer"}).json()
    assert todo["owner"]["email"] == "pat@steuartnutrition.com" and not todo["private"]
    assert call(raw, "PATCH", f"/api/v1/todos/{todo['id']}", {"done": True}).json()["done"] is True
    private = call(raw, "POST", "/api/v1/todos", {"title": "Call mom"}).json()
    assert private["private"] and Todo.objects.get(pk=private["id"]).owner == member

    h = call(raw, "POST", "/api/v1/headlines", {"team": "kentucky", "text": "Record week", "kind": "employee"})
    assert h.status_code == 201 and Headline.objects.get().author == member


def test_unknown_arguments_and_routes(token, quarter):
    _, raw = token
    assert call(raw, "POST", "/api/v1/issues", {"title": "x", "bogus": 1}).status_code == 400
    assert call(raw, "GET", "/api/v1/nothing").status_code == 404
    assert call(raw, "DELETE", "/api/v1/rocks").status_code == 405


def test_mcp_handshake_and_tools(token, member, teams, quarter):
    _, raw = token
    init = mcp(raw, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}).json()
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"]["tools"]
    assert mcp(raw, "notifications/initialized", rid=None).status_code == 202
    names = {t["name"] for t in mcp(raw, "tools/list").json()["result"]["tools"]}
    assert {"set_measurable_value", "add_rock_update", "create_issue", "create_todo", "create_headline", "get_meeting"} <= names
    assert Client().get("/mcp").status_code == 405
    assert Client().post("/mcp", data="{}", content_type="application/json").status_code == 401


def test_mcp_tool_call_writes_and_logs(token, member, teams, quarter):
    _, raw = token
    rock = Rock.objects.create(team=teams["ky"], quarter=quarter, title="Hire plant manager", owner=member)
    res = mcp(raw, "tools/call", {"name": "add_rock_update", "arguments": {"rock_id": rock.pk, "rag": "green", "note": "Two finalists"}}).json()
    assert res["result"]["isError"] is False
    assert res["result"]["structuredContent"]["rag"] == "green"
    log = AuditLog.objects.get()
    assert log.channel == "mcp" and log.action == "add_rock_update" and log.is_write and log.object_id == str(rock.pk)

    err = mcp(raw, "tools/call", {"name": "add_rock_update", "arguments": {"rock_id": rock.pk, "rag": "red"}}).json()
    assert err["result"]["isError"] is True
    assert mcp(raw, "tools/call", {"name": "drop_tables"}).json()["error"]["code"] == -32602


def test_mcp_meeting_rating(token, member, teams, quarter):
    meeting = Meeting.objects.create(team=teams["ky"], quarter=quarter)
    res = mcp(token[1], "tools/call", {"name": "rate_meeting", "arguments": {"meeting_id": meeting.pk, "rating": 9}}).json()
    assert not res["result"]["isError"]
    assert MeetingRating.objects.get(meeting=meeting).rating == 9 and MeetingRating.objects.get().user == member


def test_token_page_creates_and_revokes(as_user, member):
    c = as_user(member)
    r = c.post("/settings/api/", {"label": "Cursor", "scope": "write", "expires": "90"})
    assert r.status_code == 302
    page = c.get("/settings/api/")
    raw = page.context["new"]["raw"]
    assert raw.startswith("sneos_") and raw in page.content.decode()
    assert raw not in c.get("/settings/api/").content.decode()
    token = ApiToken.objects.get()
    assert token.expires_at is not None
    c.post(f"/settings/api/{token.pk}/revoke/")
    token.refresh_from_db()
    assert token.revoked_at and ApiToken.find(raw) is None


def test_cannot_revoke_someone_elses_token(as_user, member, other):
    token, _ = ApiToken.issue(other, "Theirs")
    assert as_user(member).post(f"/settings/api/{token.pk}/revoke/").status_code == 404


def test_session_read_and_brainstorm(token, member, other, teams, quarter):
    from planning.models import Session

    _, raw = token
    s = Session.objects.create(team=teams["ky"], quarter=quarter, kind=Session.ANNUAL)
    r = call(raw, "POST", f"/api/v1/sessions/{s.pk}/items", {"step": "swot", "kind": "swot_threat", "text": "Freight costs"})
    assert r.status_code == 200, r.content
    assert call(raw, "POST", f"/api/v1/sessions/{s.pk}/items", {"step": "swot", "kind": "lesson", "text": "x"}).status_code == 400
    data = call(raw, "GET", f"/api/v1/sessions/{s.pk}").json()
    assert data["items"][0]["text"] == "Freight costs" and len(data["agenda"]) == 10
    assert AuditLog.objects.filter(is_write=True, ok=True, object_type="session", object_id=str(s.pk)).exists()
    other_s = Session.objects.create(team=teams["lr"], quarter=quarter)
    assert call(raw, "POST", f"/api/v1/sessions/{other_s.pk}/items", {"step": "segue", "kind": "news", "text": "x"}).status_code == 403
