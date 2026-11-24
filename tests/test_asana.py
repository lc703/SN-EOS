"""Send to Asana for to-dos, with the Asana HTTP layer faked. Nothing here talks to the network."""

import datetime as dt
import importlib
import json

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from api import tools
from api.models import ApiToken
from core import asana_client
from core.models import AppSetting, Quarter, User
from todos.models import Todo

HTMX = {"HTTP_HX_REQUEST": "true"}


class Resp:
    def __init__(self, data, status=200, next_offset=None):
        self.status_code, self._data, self.text, self._next = status, data, str(data), next_offset

    def json(self):
        if self.status_code >= 400:
            return self._data
        body = {"data": self._data}
        if self._next:
            body["next_page"] = {"offset": self._next}
        return body


class FakeAsana:
    """Just enough of the Asana API: projects, sections, members, users, tasks."""

    def __init__(self):
        self.calls, self.tasks, self.members = [], {}, set()
        self.projects = []
        self.users = [
            {"gid": "U-KIM", "email": "kim@steuartnutrition.com"},
            {"gid": "U-ADA", "email": "ada.work@asana-login.example"},
            {"gid": "U-LEE", "email": "lee@steuartnutrition.com"},
        ]
        self.completed = {"T1": "2026-10-06T10:00:00.000Z"}
        self.fail = None

    def count(self, method, path):
        return sum(1 for c in self.calls if c[0] == method and c[1] == path)

    def __call__(self, method, url, **kw):
        path = url.replace(asana_client.API, "")
        self.calls.append((method, path, kw))
        if self.fail:
            return Resp({"errors": [{"message": self.fail}]}, 403)
        body = kw.get("json", {}).get("data", {})
        if method == "GET" and path == "/projects":
            return Resp(self.projects)
        if method == "POST" and path == "/projects":
            return Resp({"gid": "P1"})
        if method == "GET" and path == "/projects/P1/sections":
            return Resp([{"gid": "S-KY", "name": "Kentucky"}])
        if method == "POST" and path == "/projects/P1/sections":
            return Resp({"gid": f"S-{body['name']}"})
        if method == "POST" and path.endswith("/addMembers"):
            self.members.add(body["members"])
            return Resp({"gid": "P1"})
        if method == "GET" and path == "/users":
            if kw["params"].get("offset") == "page2":
                return Resp(self.users[2:])
            return Resp(self.users[:2], next_offset="page2")
        if method == "POST" and path == "/tasks":
            gid = f"T{len(self.tasks) + 1}"
            self.tasks[gid] = body
            return Resp({"gid": gid})
        if method == "PUT" and path.startswith("/tasks/"):
            self.tasks.setdefault(path.split("/")[-1], {}).update(body)
            return Resp({"gid": path.split("/")[-1]})
        if method == "GET" and path == "/tasks":
            return Resp([{"gid": g, "completed": True, "completed_at": at} for g, at in self.completed.items()]
                        + [{"gid": "T-OPEN", "completed": False}])
        return Resp({"errors": [{"message": f"unexpected {method} {path}"}]}, 400)


@pytest.fixture
def fake(db, settings, monkeypatch):
    settings.ASANA_PAT = "test-token"
    settings.ASANA_WORKSPACE_GID = "W1"
    settings.ASANA_TEAM_GID = "TEAM1"
    settings.ASANA_PROJECT_GID = ""
    settings.SITE_URL = "https://eos.example"
    f = FakeAsana()
    monkeypatch.setattr(asana_client.requests, "request", f)
    return f


@pytest.fixture
def q(db):
    return Quarter.objects.create(name="Q4 2026", start_date=dt.date(2026, 10, 1), end_date=dt.date(2026, 12, 31), is_current=True)


def make_todo(owner, team, title="Call the supplier", **kw):
    kw.setdefault("due_date", dt.date(2026, 10, 12))
    return Todo.objects.create(team=team, owner=owner, title=title, created_by=owner, **kw)


# ---- the adapter ------------------------------------------------------------------------

def test_send_creates_project_sections_and_task(fake, member, teams, q):
    from rocks.models import Rock

    rock = Rock.objects.create(quarter=q, team=teams["ky"], title="Blending system in, wash room configured, rooms 5 and 6 built", owner=member)
    t = make_todo(member, teams["ky"], notes="Ask about lead times", rock=rock)
    gid = asana_client.send_todo(t)
    t.refresh_from_db()
    assert gid == "T1" and t.asana_task_gid == "T1" and t.asana_sent_at and not t.asana_unassigned
    assert t.asana_url == "https://app.asana.com/0/0/T1" and t.asana_state == "sent"
    task = fake.tasks["T1"]
    assert task["name"] == "[Blending system in, wash room configured] Call the supplier"  # parent cut to 40
    assert task["assignee"] == "U-KIM" and task["due_on"] == "2026-10-12"
    assert task["projects"] == ["P1"] and task["memberships"] == [{"project": "P1", "section": "S-KY"}]
    assert task["notes"].startswith("Ask about lead times\n\n---\nTeam: Kentucky\nQuarter: Q4 2026\nOwner: Kim Member")
    assert f"https://eos.example/todos/{t.pk}/" in task["notes"]
    project_call = next(c for c in fake.calls if c[0] == "POST" and c[1] == "/projects")
    assert project_call[2]["json"]["data"]["team"] == "TEAM1" and project_call[2]["json"]["data"]["name"] == "Strategic Action"
    assert fake.members == {"U-KIM"}
    # The users list is followed across pages, and sending again never makes a second task.
    assert fake.count("GET", "/users") == 2
    asana_client.send_todo(t)
    assert len(fake.tasks) == 1


def test_an_existing_strategic_action_project_is_reused(fake, member, teams, q):
    fake.projects = [{"gid": "OTHER", "name": "Something else"}, {"gid": "P1", "name": "Strategic Action"}]
    asana_client.send_todo(make_todo(member, teams["ky"]))
    assert fake.count("POST", "/projects") == 0
    assert AppSetting.get("asana_project_gid") == "P1"
    # And ASANA_PROJECT_GID wins over any lookup.


def test_project_gid_setting_skips_lookup(fake, settings, member, teams, q):
    settings.ASANA_PROJECT_GID = "P1"
    asana_client.send_todo(make_todo(member, teams["ky"]))
    assert fake.count("GET", "/projects") == 0 and fake.count("POST", "/projects") == 0
    assert fake.tasks["T1"]["projects"] == ["P1"]


def test_unknown_team_goes_to_the_company_section(fake, member, teams, q):
    from core.models import Team

    other = Team.objects.create(name="Sales")
    asana_client.send_todo(make_todo(member, other))
    assert fake.tasks["T1"]["memberships"] == [{"project": "P1", "section": "S-Company"}]


def test_unmatched_email_is_unassigned_and_asana_email_overrides(fake, admin, member, teams, q):
    t = make_todo(admin, teams["company"])  # admin@ is not in Asana
    asana_client.send_todo(t)
    t.refresh_from_db()
    assert t.asana_unassigned and "assignee" not in fake.tasks[t.asana_task_gid]
    assert fake.members == set()
    other = make_todo(admin, teams["company"], title="Second")
    admin.asana_email = "ada.work@asana-login.example"
    admin.save()
    asana_client.send_todo(other)
    assert fake.tasks[other.asana_task_gid]["assignee"] == "U-ADA"


def test_late_asana_signup_gets_assigned(fake, admin, teams, q):
    t = make_todo(admin, teams["company"])
    asana_client.send_todo(t)
    assert asana_client.fix_unassigned() == 0  # the miss is remembered for an hour
    fake.users.append({"gid": "U-NEW", "email": "admin@steuartnutrition.com"})
    assert asana_client.fix_unassigned() == 0
    AppSetting.put("asana_user_admin@steuartnutrition.com", "-|" + (timezone.now() - dt.timedelta(hours=2)).isoformat())
    assert asana_client.fix_unassigned() == 1
    t.refresh_from_db()
    assert not t.asana_unassigned and "U-NEW" in fake.members and fake.tasks[t.asana_task_gid]["assignee"] == "U-NEW"


def test_private_todos_are_never_sent(fake, member, teams, q):
    t = make_todo(member, teams["ky"], is_private=True)
    with pytest.raises(asana_client.AsanaError, match="Private"):
        asana_client.send_todo(t)
    assert not fake.calls


def test_asana_errors_leave_the_todo_unsent(fake, member, teams, q):
    t = make_todo(member, teams["ky"])
    fake.fail = "Not Authorized"
    with pytest.raises(asana_client.AsanaError, match="Asana said: Not Authorized"):
        asana_client.send_todo(t)
    t.refresh_from_db()
    assert t.asana_task_gid == "" and t.asana_state == "none"


def test_network_trouble_is_an_asana_error(db, settings, monkeypatch, member, teams, q):
    import requests

    settings.ASANA_PAT, settings.ASANA_WORKSPACE_GID = "x", "W1"

    def boom(*a, **k):
        raise requests.Timeout()

    monkeypatch.setattr(asana_client.requests, "request", boom)
    with pytest.raises(asana_client.AsanaError, match="Could not reach Asana"):
        asana_client.send_todo(make_todo(member, teams["ky"]))


# ---- completion comes back --------------------------------------------------------------

def test_completion_in_asana_checks_the_todo_off(fake, member, teams, q):
    a, b = make_todo(member, teams["ky"]), make_todo(member, teams["ky"], title="Other")
    asana_client.send_todo(a)
    asana_client.send_todo(b)
    out = call_command("sync_asana")
    a.refresh_from_db()
    b.refresh_from_db()
    assert out is None
    assert a.done and a.done_at.isoformat().startswith("2026-10-06T10:00") and a.asana_completed_at and a.asana_state == "done"
    assert not b.done and b.asana_completed_at is None
    assert AppSetting.get("asana_last_sync")
    assert asana_client.sync_completed() == 0  # already recorded


def test_reopened_todo_does_not_say_done_in_asana(fake, member, teams, q):
    t = make_todo(member, teams["ky"])
    asana_client.send_todo(t)
    asana_client.sync_completed()
    t.refresh_from_db()
    t.set_done(False)
    assert t.asana_state == "sent"


def test_todos_page_syncs_at_most_every_ten_minutes(fake, as_user, member, teams, q):
    t = make_todo(member, teams["ky"])
    asana_client.send_todo(t)
    c = as_user(member, teams["ky"])
    c.get("/todos/")
    assert Todo.objects.get(pk=t.pk).done
    syncs = fake.count("GET", "/tasks")
    c.get("/todos/")
    assert fake.count("GET", "/tasks") == syncs


def test_sync_never_breaks_the_page(fake, as_user, member, teams, q):
    asana_client.send_todo(make_todo(member, teams["ky"]))
    AppSetting.put("asana_last_sync", "")
    fake.fail = "boom"
    assert as_user(member, teams["ky"]).get("/todos/").status_code == 200


def test_not_configured_hides_everything_and_does_nothing(db, settings, as_user, member, teams, q, monkeypatch):
    settings.ASANA_PAT = ""
    called = []
    monkeypatch.setattr(asana_client.requests, "request", lambda *a, **k: called.append(a))
    t = make_todo(member, teams["ky"])
    c = as_user(member, teams["ky"])
    assert b"Send to Asana" not in c.get("/todos/").content and b"Send to Asana" not in c.get(f"/todos/{t.pk}/").content
    r = c.post(f"/todos/{t.pk}/asana/", {"partial": "1"}, **HTMX)
    assert b"not connected" in r.content
    asana_client.maybe_sync()
    call_command("sync_asana")
    assert not called and not Todo.objects.get(pk=t.pk).asana_task_gid


# ---- the buttons ------------------------------------------------------------------------

def test_row_shows_send_button_then_the_link(fake, as_user, member, teams, q):
    fake.completed = {}
    t = make_todo(member, teams["ky"])
    c = as_user(member, teams["ky"])
    page = c.get("/todos/").content.decode()
    assert "Send to Asana" in page and f'hx-post="/todos/{t.pk}/asana/"' in page
    r = c.post(f"/todos/{t.pk}/asana/", {"partial": "1"}, **HTMX)
    html = r.content.decode()
    assert r.status_code == 200 and f'id="todo-{t.pk}"' in html and "In Asana" in html
    assert "https://app.asana.com/0/0/T1" in html and "Send to Asana" not in html
    assert "In Asana" in c.get("/todos/").content.decode()


def test_double_send_makes_one_task(fake, as_user, member, teams, q):
    t = make_todo(member, teams["ky"])
    c = as_user(member, teams["ky"])
    c.post(f"/todos/{t.pk}/asana/", {"partial": "1"}, **HTMX)
    c.post(f"/todos/{t.pk}/asana/", {"partial": "1"}, **HTMX)
    c.post(f"/todos/{t.pk}/asana/", {"next": "/todos/"})
    assert len(fake.tasks) == 1 and fake.count("POST", "/tasks") == 1


def test_plain_post_redirects_with_a_message(fake, as_user, member, teams, q):
    t = make_todo(member, teams["ky"])
    r = as_user(member, teams["ky"]).post(f"/todos/{t.pk}/asana/", {"next": "/todos/"}, follow=True)
    assert r.redirect_chain[-1][0] == "/todos/" and "Sent to Asana." in r.content.decode()


def test_unassigned_is_said_out_loud(fake, as_user, admin, teams, q):
    t = make_todo(admin, teams["company"])
    c = as_user(admin, teams["company"])
    html = c.post(f"/todos/{t.pk}/asana/", {"partial": "1"}, **HTMX).content.decode()
    assert "unassigned" in html
    t2 = make_todo(admin, teams["company"], title="Again")
    page = c.post(f"/todos/{t2.pk}/asana/", {"next": "/todos/"}, follow=True).content.decode()
    assert "was not found in Asana, so it is unassigned" in page


def test_asana_error_shows_on_the_row(fake, as_user, member, teams, q):
    t = make_todo(member, teams["ky"])
    fake.fail = "Not Authorized"
    html = as_user(member, teams["ky"]).post(f"/todos/{t.pk}/asana/", {"partial": "1"}, **HTMX).content.decode()
    assert "Not sent to Asana: Asana said: Not Authorized" in html and "Send to Asana" in html
    assert not Todo.objects.get(pk=t.pk).asana_task_gid


def test_only_people_who_can_edit_may_send(fake, as_user, member, other, teams, q):
    t = make_todo(member, teams["ky"])
    assert as_user(other).post(f"/todos/{t.pk}/asana/", {"partial": "1"}, **HTMX).status_code == 403
    assert Client().post(f"/todos/{t.pk}/asana/").status_code == 302  # login redirect
    assert not fake.calls
    # Someone who can't edit doesn't get the button either, only the link once it exists.
    page = as_user(other, teams["ky"]).get(f"/todos/{t.pk}/").content.decode()
    assert "Send to Asana" not in page


def test_private_todo_has_no_button_and_cannot_be_posted(fake, as_user, member, teams, q):
    t = make_todo(member, teams["ky"], is_private=True)
    c = as_user(member, teams["ky"])
    assert "data-asana-send" not in c.get("/todos/").content.decode()
    r = c.post(f"/todos/{t.pk}/asana/", {"partial": "1"}, **HTMX)
    assert "Private to-dos stay in SN EOS" in r.content.decode() and not fake.calls


def test_edit_page_has_the_asana_panel(fake, as_user, member, teams, q):
    t = make_todo(member, teams["ky"])
    c = as_user(member, teams["ky"])
    page = c.get(f"/todos/{t.pk}/").content.decode()
    assert "Send to Asana" in page and f"/todos/{t.pk}/asana/" in page
    c.post(f"/todos/{t.pk}/asana/", {"next": f"/todos/{t.pk}/"})
    page = c.get(f"/todos/{t.pk}/").content.decode()
    assert "Open in Asana" in page and "https://app.asana.com/0/0/T1" in page and "Send to Asana" not in page


def test_add_form_sends_when_ticked(fake, as_user, member, teams, q):
    c = as_user(member, teams["ky"])
    page = c.get("/todos/").content.decode()
    assert 'name="send_asana"' in page
    c.post("/todos/new/", {"title": "Auto send", "owner": member.pk, "due_date": "2026-10-20", "send_asana": "1", "next": "/todos/"})
    c.post("/todos/new/", {"title": "No send", "owner": member.pk, "due_date": "2026-10-20", "next": "/todos/"})
    c.post("/todos/new/", {"title": "Private", "owner": member.pk, "due_date": "2026-10-20", "send_asana": "1", "is_private": "1", "next": "/todos/"})
    assert Todo.objects.get(title="Auto send").asana_task_gid
    assert Todo.objects.get(title="No send").asana_task_gid == ""
    assert Todo.objects.get(title="Private").asana_task_gid == ""
    assert len(fake.tasks) == 1


def test_rock_page_add_form_can_send_too(fake, as_user, member, teams, q):
    from rocks.models import Rock

    rock = Rock.objects.create(quarter=q, team=teams["ky"], title="Cross-train", owner=member)
    c = as_user(member, teams["ky"])
    c.post(f"/rocks/{rock.pk}/todos/", {"title": "Book trainer", "owner": member.pk, "due_date": "2026-10-20", "send_asana": "1"})
    todo = Todo.objects.get(title="Book trainer")
    assert todo.asana_task_gid and fake.tasks[todo.asana_task_gid]["name"] == "[Cross-train] Book trainer"


def test_a_failed_send_on_add_still_creates_the_todo(fake, as_user, member, teams, q):
    fake.fail = "Not Authorized"
    r = as_user(member, teams["ky"]).post(
        "/todos/new/", {"title": "Keep me", "owner": member.pk, "due_date": "2026-10-20", "send_asana": "1", "next": "/todos/"}, follow=True)
    assert Todo.objects.get(title="Keep me").asana_task_gid == "" and "Not sent to Asana" in r.content.decode()


def test_editing_notes_updates_the_asana_task(fake, as_user, member, teams, q):
    t = make_todo(member, teams["ky"], notes="500 rolls")
    asana_client.send_todo(t)
    c = as_user(member, teams["ky"])
    form = {"title": t.title, "owner": member.pk, "due_date": "2026-10-12", "notes": "600 rolls", "next": "/todos/"}
    c.post(f"/todos/{t.pk}/", form)
    puts = [x for x in fake.calls if x[0] == "PUT"]
    assert puts and puts[-1][1] == "/tasks/T1" and puts[-1][2]["json"]["data"]["notes"].startswith("600 rolls")
    c.post(f"/todos/{t.pk}/", form)  # unchanged: Asana is not called again
    assert len([x for x in fake.calls if x[0] == "PUT"]) == len(puts)


def test_dashboard_rows_show_the_link(fake, as_user, member, teams, q):
    t = make_todo(member, teams["ky"], due_date=timezone.localdate())
    asana_client.send_todo(t)
    assert "https://app.asana.com/0/0/T1" in as_user(member, teams["ky"]).get("/").content.decode()


# ---- REST and MCP -----------------------------------------------------------------------

def test_api_and_mcp_expose_the_asana_link(fake, member, teams, q):
    sent, plain = make_todo(member, teams["ky"]), make_todo(member, teams["ky"], title="Not sent")
    asana_client.send_todo(sent)
    _, raw = ApiToken.issue(member, "t")
    bearer = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
    rows = {r["title"]: r for r in Client().get("/api/v1/todos", **bearer).json()["data"]}
    assert rows["Call the supplier"]["in_asana"] is True
    assert rows["Call the supplier"]["asana_url"] == "https://app.asana.com/0/0/T1"
    assert rows["Call the supplier"]["asana_state"] == "sent" and rows["Call the supplier"]["asana_unassigned"] is False
    assert rows["Not sent"]["in_asana"] is False and rows["Not sent"]["asana_url"] is None and rows["Not sent"]["asana_state"] == "none"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_todos", "arguments": {}}}
    r = Client().post("/mcp", json.dumps(body), content_type="application/json", **bearer).json()["result"]
    assert not r["isError"] and "https://app.asana.com/0/0/T1" in r["content"][0]["text"]
    listed = {t["name"]: t for t in tools.TOOLS.values()}
    assert "Asana" in listed["list_todos"]["description"]


def test_update_todo_tool_pushes_notes_and_warns_on_failure(fake, member, teams, q):
    t = make_todo(member, teams["ky"], notes="v1")
    asana_client.send_todo(t)
    actor = tools.Actor(user=member)
    out = tools.call(actor, "update_todo", {"todo_id": t.pk, "notes": "v2"})
    assert out["asana_url"] and "asana_warning" not in out
    assert fake.tasks["T1"]["notes"].startswith("v2")
    fake.fail = "Not Authorized"
    out = tools.call(actor, "update_todo", {"todo_id": t.pk, "notes": "v3"})
    assert "asana_warning" in out
    assert tools.call(actor, "update_todo", {"todo_id": t.pk, "title": "Renamed"})["title"] == "Renamed"


# ---- Battle Planner import --------------------------------------------------------------

def _import(*args):
    from io import StringIO
    from pathlib import Path

    out = StringIO()
    call_command("import_battle_planner", str(Path(__file__).parent / "fixtures" / "battle_planner_sample.json"), *args, stdout=out)
    return out.getvalue()


def test_import_brings_over_asana_links_and_emails(db):
    _import()
    fixed = Todo.objects.get(title="Fix metal detector")
    assert fixed.asana_task_gid == "1200000000000002" and fixed.asana_url.endswith("/1200000000000002")
    assert fixed.done and fixed.asana_completed_at and fixed.asana_sent_at and not fixed.asana_unassigned
    draft = Todo.objects.get(title="Draft hiring plan")
    assert draft.asana_task_gid == "1200000000000003" and draft.asana_unassigned and not draft.done
    assert draft.asana_state == "sent"
    assert Todo.objects.get(title="Send quote to customer").asana_task_gid == ""
    assert User.objects.get(email="casey@steuartnutrition.com").asana_email == "casey@asana-login.example"
    assert User.objects.get(email="alex@steuartnutrition.com").asana_email == ""


def test_import_never_wipes_a_link_made_in_sn_eos_and_fills_gaps(db):
    _import()
    quote = Todo.objects.get(title="Send quote to customer")  # no link in the export
    quote.asana_task_gid, quote.asana_sent_at = "SENT-FROM-EOS", timezone.now()
    quote.save()
    draft = Todo.objects.get(title="Draft hiring plan")
    draft.asana_task_gid = ""
    draft.save()
    casey = User.objects.get(email="casey@steuartnutrition.com")
    casey.asana_email = ""
    casey.save()
    for args in ((), ("--refresh",), ("--sync",)):
        _import(*args)
        assert Todo.objects.get(title="Send quote to customer").asana_task_gid == "SENT-FROM-EOS"
        assert Todo.objects.get(title="Draft hiring plan").asana_task_gid == "1200000000000003"
        assert User.objects.get(email="casey@steuartnutrition.com").asana_email == "casey@asana-login.example"
    assert Todo.objects.exclude(asana_task_gid="").count() == 3


def test_migration_moves_legacy_links_into_real_fields(db, member, teams):
    mig = importlib.import_module("todos.migrations.0002_asana")
    t = make_todo(member, teams["ky"], legacy={"asana_task_gid": "999", "asana_completed_at": "2026-10-08T12:00:00Z"})
    plain = make_todo(member, teams["ky"], title="Plain")
    mig.backfill_asana_links(django_apps, None)
    t.refresh_from_db()
    plain.refresh_from_db()
    assert t.asana_task_gid == "999" and t.asana_completed_at.isoformat().startswith("2026-10-08T12:00") and plain.asana_task_gid == ""
    core_mig = importlib.import_module("core.migrations.0002_asana")
    member.legacy = {"asana_email": "kim@asana-login.example"}
    member.save()
    core_mig.backfill_asana_email(django_apps, None)
    member.refresh_from_db()
    assert member.asana_email == "kim@asana-login.example"


def test_a_stale_copy_of_a_sent_todo_does_not_send_again(fake, member, teams, q):
    first = make_todo(member, teams["ky"])
    stale = Todo.objects.get(pk=first.pk)  # two people had the page open
    asana_client.send_todo(first)
    assert asana_client.send_todo(stale) == "T1"
    assert len(fake.tasks) == 1 and stale.asana_task_gid == "T1" and stale.asana_sent_at
