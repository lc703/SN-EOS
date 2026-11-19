import datetime as dt
import json
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from api.models import ApiToken, AuditLog
from core.models import Quarter, monday_of
from issues.models import Issue
from rocks.models import Rock, RockUpdate
from scorecard.models import Measurable, ScoreEntry
from todos.models import Todo


@pytest.fixture
def cur_q(db):
    q = Quarter.for_calendar(timezone.localdate())
    Quarter.objects.update(is_current=False)
    q.is_current = True
    q.save()
    return q


def bearer(raw):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def rpc(raw, method, params=None, mid=1):
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if mid is not None:
        body["id"] = mid
    return Client().post("/mcp", json.dumps(body), content_type="application/json", **bearer(raw))


def test_token_is_shown_once_and_only_its_hash_is_stored(member):
    token, raw = ApiToken.issue(member, "Laptop")
    assert raw.startswith("sneos_") and raw not in token.key_hash and token.prefix in raw
    assert ApiToken.authenticate(raw) == token
    assert ApiToken.authenticate(raw + "x") is None
    token.revoked_at = timezone.now()
    token.save()
    assert ApiToken.authenticate(raw) is None


def test_token_page_creates_and_revokes(as_user, member, other):
    c = as_user(member)
    r = c.post("/settings/api/", {"name": "Claude", "access": "read"})
    assert r.status_code == 200 and b"sneos_" in r.content
    token = ApiToken.objects.get(user=member)
    assert not token.can_write
    assert as_user(other).post(f"/settings/api/{token.pk}/revoke/").status_code == 403
    c.post(f"/settings/api/{token.pk}/revoke/")
    token.refresh_from_db()
    assert token.revoked_at is not None
    assert AuditLog.objects.filter(action="token.revoke", user=member).exists()


def test_rest_requires_a_valid_token(member):
    assert Client().get("/api/v1/me").status_code == 401
    assert Client().get("/api/v1/me", **bearer("sneos_nope")).status_code == 401
    _, raw = ApiToken.issue(member, "t")
    r = Client().get("/api/v1/me", **bearer(raw))
    assert r.status_code == 200 and r.json()["data"]["user"]["email"] == member.email
    assert Client().get("/api/v1/nowhere", **bearer(raw)).status_code == 404
    assert Client().delete("/api/v1/issues", **bearer(raw)).status_code == 405


def test_rest_writes_are_attributed_and_logged(member, teams, cur_q):
    m = Measurable.objects.create(team=teams["ky"], title="Tons", owner=member, goal=Decimal(10))
    _, raw = ApiToken.issue(member, "t")
    r = Client().post(f"/api/v1/measurables/{m.pk}/values", json.dumps({"value": "12"}), content_type="application/json", **bearer(raw))
    assert r.status_code == 200, r.content
    entry = ScoreEntry.objects.get(measurable=m)
    assert entry.value == Decimal(12) and entry.updated_by == member and entry.week_start == monday_of(timezone.localdate())
    log = AuditLog.objects.get(action="scorecard.set_value")
    assert log.user == member and log.source == AuditLog.API and log.token.user == member

    r = Client().post("/api/v1/issues", json.dumps({"title": "Mixer noise", "team": "kentucky"}), content_type="application/json", **bearer(raw))
    assert r.status_code == 201
    issue = Issue.objects.get(title="Mixer noise")
    assert issue.created_by == member and issue.team == teams["ky"]


def test_read_only_token_cannot_write(member, teams, cur_q):
    _, raw = ApiToken.issue(member, "ro", can_write=False)
    r = Client().post("/api/v1/todos", json.dumps({"title": "x"}), content_type="application/json", **bearer(raw))
    assert r.status_code == 403
    assert not Todo.objects.exists()
    tools = rpc(raw, "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "list_rocks" in names and "create_todo" not in names


def test_api_respects_ownership(member, other, teams, cur_q):
    m = Measurable.objects.create(team=teams["lr"], title="Their number", owner=other)
    rock = Rock.objects.create(quarter=cur_q, team=teams["lr"], title="Their rock", owner=other)
    _, raw = ApiToken.issue(member, "t")
    r = Client().post(f"/api/v1/measurables/{m.pk}/values", json.dumps({"value": 3}), content_type="application/json", **bearer(raw))
    assert r.status_code == 403 and not ScoreEntry.objects.exists()
    r = Client().post(f"/api/v1/rocks/{rock.pk}/updates", json.dumps({"color": "green"}), content_type="application/json", **bearer(raw))
    assert r.status_code == 403 and not RockUpdate.objects.exists()


def test_private_todos_stay_private(member, ky_peer, teams, cur_q):
    Todo.objects.create(team=teams["ky"], title="Secret", owner=ky_peer, is_private=True)
    Todo.objects.create(team=teams["ky"], title="Shared", owner=ky_peer)
    _, raw = ApiToken.issue(member, "t")
    r = Client().get("/api/v1/todos", {"team": "kentucky", "owner": "all"}, **bearer(raw))
    titles = [t["title"] for t in r.json()["data"]]
    assert "Shared" in titles and "Secret" not in titles


def test_mcp_handshake_and_tool_call(member, teams, cur_q):
    rock = Rock.objects.create(quarter=cur_q, team=teams["ky"], title="Cross-train", owner=member)
    _, raw = ApiToken.issue(member, "Claude")
    init = rpc(raw, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}}).json()
    assert init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"]
    assert rpc(raw, "notifications/initialized", mid=None).status_code == 202
    tools = {t["name"]: t for t in rpc(raw, "tools/list").json()["result"]["tools"]}
    assert {"set_measurable_value", "update_rock_status", "create_issue", "create_todo", "add_headline", "get_l10"} <= set(tools)
    assert tools["update_rock_status"]["inputSchema"]["required"] == ["rock_id", "color"]

    red = rpc(raw, "tools/call", {"name": "update_rock_status", "arguments": {"rock_id": rock.pk, "color": "red"}}).json()["result"]
    assert red["isError"] and "recovery plan" in red["content"][0]["text"]
    ok = rpc(raw, "tools/call", {"name": "update_rock_status", "arguments": {
        "rock_id": rock.pk, "color": "red", "note": "Trainer sick", "recovery_plan": "New trainer Monday"}}).json()["result"]
    assert not ok["isError"]
    rock.refresh_from_db()
    assert rock.status == Rock.OFF_TRACK
    upd = RockUpdate.objects.get(rock=rock)
    assert upd.author == member and upd.recovery_plan == "New trainer Monday"
    assert AuditLog.objects.filter(source=AuditLog.MCP, user=member, object_type="rock").exists()

    mine = rpc(raw, "tools/call", {"name": "my_90", "arguments": {}}).json()["result"]
    assert mine["structuredContent"]["rocks"][0]["title"] == "Cross-train"


def test_mcp_errors(member):
    assert Client().post("/mcp", "{}", content_type="application/json").status_code == 401
    _, raw = ApiToken.issue(member, "t")
    assert Client().get("/mcp", **bearer(raw)).status_code == 405
    assert Client().post("/mcp", "not json", content_type="application/json", **bearer(raw)).status_code == 400
    unknown = rpc(raw, "tools/call", {"name": "drop_tables", "arguments": {}}).json()["result"]
    assert unknown["isError"]
    assert rpc(raw, "nope").json()["error"]["code"] == -32601


def test_l10_tools(member, teams, cur_q):
    from meetings.models import Meeting

    meeting = Meeting.objects.create(team=teams["ky"], quarter=cur_q, date=timezone.localdate())
    meeting.attendees.add(member)
    _, raw = ApiToken.issue(member, "t")
    c = Client()
    r = c.post(f"/api/v1/l10/{meeting.pk}/cascading-messages", json.dumps({"message": "Plant closed Friday"}), content_type="application/json", **bearer(raw))
    assert r.status_code == 201, r.content
    r = c.post(f"/api/v1/l10/{meeting.pk}/rating", json.dumps({"rating": 9}), content_type="application/json", **bearer(raw))
    assert r.status_code == 200
    meeting.refresh_from_db()
    assert "Plant closed Friday" in meeting.cascading_messages and meeting.average_rating == 9
    r = c.post("/api/v1/headlines", json.dumps({"text": "Big order", "team": "kentucky"}), content_type="application/json", **bearer(raw))
    assert r.status_code == 201
    data = c.get("/api/v1/l10", {"team": "kentucky"}, **bearer(raw)).json()["data"]
    assert data["meeting"]["id"] == meeting.pk and data["meeting"]["average_rating"] == 9


def test_audit_log_page_scopes_to_viewer(as_user, admin, member, other):
    AuditLog.objects.create(user=member, source=AuditLog.API, action="todo.create", summary="mine")
    AuditLog.objects.create(user=other, source=AuditLog.MCP, action="todo.create", summary="theirs")
    mine = as_user(member).get("/settings/audit/").content.decode()
    assert "mine" in mine and "theirs" not in mine
    everyone = as_user(admin).get("/settings/audit/").content.decode()
    assert "mine" in everyone and "theirs" in everyone


def test_week_argument_backfills(member, teams, cur_q):
    m = Measurable.objects.create(team=teams["ky"], title="Tons", owner=member)
    _, raw = ApiToken.issue(member, "t")
    last_week = timezone.localdate() - dt.timedelta(days=7)
    rpc(raw, "tools/call", {"name": "set_measurable_value", "arguments": {"measurable_id": m.pk, "value": 5, "week": last_week.isoformat()}})
    assert ScoreEntry.objects.get(measurable=m).week_start == monday_of(last_week)
