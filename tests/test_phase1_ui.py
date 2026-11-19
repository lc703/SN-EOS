import datetime as dt
import json
import os
from decimal import Decimal

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.utils import timezone

from core.models import Quarter, monday_of
from issues.models import Issue
from people.models import ConversationScore, OneOnOne, SuccessStatement
from planning.models import Session, SessionItem
from rocks.models import Rock, RockUpdate
from rocks.services import record_update
from scorecard.models import Measurable, ScoreEntry
from vision.models import CoreProcess, CoreValue, Seat

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def cur_q(db):
    q = Quarter.for_calendar(timezone.localdate())
    Quarter.objects.update(is_current=False)
    q.is_current = True
    q.save()
    return q


# ---------------- Accountability Chart ----------------

def test_chart_shows_status_counts_and_whole_company_for_leadership(as_user, admin, teams):
    Seat.objects.create(team=teams["company"], title="Integrator", person=admin)
    Seat.objects.create(team=teams["ky"], title="Plant Manager", status=Seat.OPEN)
    Seat.objects.create(team=teams["ky"], title="Logistics", status=Seat.FUTURE)
    page = as_user(admin, teams["company"]).get("/chart/")
    assert page.context["whole"] and page.context["counts"]["open"] == 1 and page.context["counts"]["future"] == 1
    team_only = as_user(admin, teams["company"]).get("/chart/?all=0")
    assert team_only.context["counts"]["total"] == 1
    listed = as_user(admin, teams["ky"]).get("/chart/?view=list&status=open")
    assert [s.title for s, _ in listed.context["seats"]] == ["Plant Manager"]


def test_filled_status_without_a_person_counts_as_open(teams):
    seat = Seat.objects.create(team=teams["ky"], title="Empty")
    assert seat.display_status == Seat.OPEN


def test_seat_move_rejects_cycles_and_adopts_parent_team(as_user, admin, member, teams):
    top = Seat.objects.create(team=teams["company"], title="Integrator")
    mid = Seat.objects.create(team=teams["ky"], title="Plant", parent=top)
    low = Seat.objects.create(team=teams["ky"], title="Shift", parent=mid)
    c = as_user(admin)
    assert as_user(member).post(f"/chart/seats/{mid.pk}/move/", {"parent": ""}).status_code == 403
    assert c.post(f"/chart/seats/{top.pk}/move/", {"parent": low.pk}).status_code == 400
    r = c.post(f"/chart/seats/{low.pk}/move/", {"parent": top.pk})
    assert r.json()["ok"]
    low.refresh_from_db()
    assert low.parent == top and low.team == teams["company"]
    c.post(f"/chart/seats/{low.pk}/move/", {"parent": ""})
    low.refresh_from_db()
    assert low.parent is None


def test_seat_panel_autosaves_and_refreshes_chart(as_user, admin, teams):
    seat = Seat.objects.create(team=teams["ky"], title="Plant")
    c = as_user(admin, teams["ky"])
    assert b"Plant" in c.get(f"/chart/seats/{seat.pk}/panel/", **HTMX).content
    data = {"title": "Plant Manager", "status": Seat.OPEN, "agency": "on", "team": teams["ky"].pk, "roles": "a\nb\nc"}
    r = c.post(f"/chart/seats/{seat.pk}/panel/", data, **HTMX)
    assert r.status_code == 204 and "chart:refresh" in r["HX-Trigger"]
    seat.refresh_from_db()
    assert (seat.title, seat.status, seat.agency, seat.role_list) == ("Plant Manager", Seat.OPEN, True, ["a", "b", "c"])
    bad = c.post(f"/chart/seats/{seat.pk}/panel/", {"title": "", "team": teams["ky"].pk}, **HTMX)
    assert bad.status_code == 422
    r = c.post(f"/chart/seats/{seat.pk}/panel/", {"delete": "1"}, **HTMX)
    assert "panel:close" in r["HX-Trigger"] and not Seat.objects.exists()


def test_people_flags_on_chart_are_private(as_user, admin, member, ky_peer, teams, cur_q):
    boss = Seat.objects.create(team=teams["ky"], title="Plant", person=ky_peer)
    Seat.objects.create(team=teams["ky"], title="Line", person=member, parent=boss)
    convo = OneOnOne.objects.create(person=member, manager=ky_peer, kind=OneOnOne.QUARTERLY, quarter=cur_q, gets_it=True, wants_it=True, capacity=False)
    assert convo.is_struggling
    member_view = as_user(member, teams["ky"]).get("/chart/?view=list")
    flags = {s.person_id: f for s, f in member_view.context["seats"]}
    assert flags[ky_peer.pk] is None and flags[member.pk]["struggling"]
    manager_view = as_user(ky_peer, teams["ky"]).get("/chart/?view=list")
    assert {s.person_id: f for s, f in manager_view.context["seats"]}[member.pk]["gwc"] == {"g": True, "w": True, "c": False}
    assert b"flag-struggling" in as_user(admin, teams["ky"]).get("/chart/").content


# ---------------- Rocks ----------------

def test_red_update_needs_a_recovery_plan(member, teams, cur_q):
    rock = Rock.objects.create(quarter=cur_q, team=teams["ky"], title="Cross-train", owner=member)
    with pytest.raises(ValidationError):
        record_update(rock, member, "red", "behind")
    record_update(rock, member, "red", "behind", "Trainer Monday")
    rock.refresh_from_db()
    assert rock.status == Rock.OFF_TRACK
    record_update(rock, member, "yellow", "better")
    rock.refresh_from_db()
    assert rock.status == Rock.ON_TRACK and RockUpdate.objects.count() == 1


def test_rock_update_panel(as_user, member, other, teams, cur_q):
    rock = Rock.objects.create(quarter=cur_q, team=teams["ky"], title="Cross-train", owner=member)
    c = as_user(member, teams["ky"])
    assert as_user(other).get(f"/rocks/{rock.pk}/update/").status_code == 403
    r = c.post(f"/rocks/{rock.pk}/update/", {"color": "red", "note": "late", "week": monday_of(timezone.localdate()).isoformat()}, **HTMX)
    assert r.status_code == 422 and b"recovery plan" in r.content
    r = c.post(f"/rocks/{rock.pk}/update/", {"color": "red", "note": "late", "recovery_plan": "Extra shift"}, **HTMX)
    assert r.status_code == 204 and json.loads(r["HX-Trigger"])["rock:changed"]["id"] == rock.pk
    last_week = monday_of(timezone.localdate()) - dt.timedelta(days=7)
    if last_week >= cur_q.start_date:
        c.post(f"/rocks/{rock.pk}/update/", {"color": "green", "week": last_week.isoformat()}, **HTMX)
        assert rock.updates.count() == 2
    rock.refresh_from_db()
    assert rock.status == Rock.OFF_TRACK


def test_choosing_off_track_opens_the_update_panel(as_user, member, teams, cur_q):
    rock = Rock.objects.create(quarter=cur_q, team=teams["ky"], title="Cross-train", owner=member)
    r = as_user(member, teams["ky"]).post(f"/rocks/{rock.pk}/status/", {"status": "off_track", "partial": "1"}, **HTMX)
    assert r["HX-Retarget"] == "#panel-body" and b"Recovery plan" in r.content
    rock.refresh_from_db()
    assert rock.status == Rock.ON_TRACK
    r = as_user(member, teams["ky"]).post(f"/rocks/{rock.pk}/status/", {"status": "done", "partial": "1"}, **HTMX)
    rock.refresh_from_db()
    assert rock.status == Rock.DONE


def test_rocks_list_has_strips_labels_and_reorders(as_user, admin, member, teams, cur_q):
    a = Rock.objects.create(quarter=cur_q, team=teams["ky"], title="Alpha", owner=member, sort=0)
    b = Rock.objects.create(quarter=cur_q, team=teams["ky"], title="Bravo", owner=member, sort=1)
    record_update(a, member, "green")
    page = as_user(member, teams["ky"]).get("/rocks/")
    rocks = page.context["team_rocks"]
    assert len(rocks[0].strip) == 13 and rocks[0].this_week.color == "green"
    assert b"Departmental" in page.content
    as_user(member, teams["ky"]).post("/rocks/sort/", {"ids": f"{b.pk},{a.pk}"})
    assert list(Rock.objects.filter(team=teams["ky"]).values_list("title", flat=True)) == ["Bravo", "Alpha"]
    assert as_user(member, teams["lr"]).post("/rocks/sort/", {"ids": f"{a.pk},{b.pk}"}).status_code == 403


# ---------------- Scorecard ----------------

def test_scorecard_trend_average_and_panel(as_user, member, teams, cur_q):
    m = Measurable.objects.create(team=teams["ky"], title="Tons", owner=member, goal=Decimal(10))
    yn = Measurable.objects.create(team=teams["ky"], title="Audit done", owner=member, unit=Measurable.UNIT_YESNO, goal=Decimal(1), goal_compare=Measurable.EQ)
    weeks = cur_q.weeks()[:2]
    for w, v in zip(weeks, (8, 12)):
        ScoreEntry.objects.create(measurable=m, week_start=w, value=Decimal(v))
        ScoreEntry.objects.create(measurable=yn, week_start=w, value=Decimal(v > 10))
    page = as_user(member, teams["ky"]).get("/scorecard/")
    rows = {r.measurable.title: r for r in page.context["rows"]}
    assert rows["Tons"].trailing == "10" and rows["Tons"].trailing_label == "avg" and rows["Tons"].hits == (1, 2)
    assert rows["Audit done"].trailing == "1/2"
    assert b"<svg class=\"spark\"" in page.content
    panel = as_user(member, teams["ky"]).get(f"/scorecard/{m.pk}/panel/", **HTMX)
    assert panel.status_code == 200 and b"Goal 10" in panel.content


def test_scorecard_cell_updates_trend_out_of_band(as_user, member, teams, cur_q):
    m = Measurable.objects.create(team=teams["ky"], title="Tons", owner=member, goal=Decimal(10))
    week = cur_q.weeks()[0].isoformat()
    r = as_user(member, teams["ky"]).post(f"/scorecard/{m.pk}/cell/{week}/", {"value": "11", "cols": week, "trend": "1", "trailing": "1", "mode": "scorecard"})
    assert b'id="mtd-' in r.content and b'id="mtr-' in r.content


def test_measurable_reorder(as_user, member, other, teams):
    a = Measurable.objects.create(team=teams["ky"], title="A", sort=0)
    b = Measurable.objects.create(team=teams["ky"], title="B", sort=1)
    as_user(member, teams["ky"]).post("/scorecard/sort/", {"ids": f"{b.pk},{a.pk}"})
    assert list(Measurable.objects.values_list("title", flat=True)) == ["B", "A"]
    assert as_user(other, teams["ky"]).post("/scorecard/sort/", {"ids": f"{a.pk},{b.pk}"}).status_code == 403


# ---------------- Quarterly Conversations ----------------

def _manager_setup(teams, member, ky_peer):
    boss = Seat.objects.create(team=teams["ky"], title="Plant", person=ky_peer)
    Seat.objects.create(team=teams["ky"], title="Line", person=member, parent=boss)


def test_quarterly_conversation_grid(as_user, member, ky_peer, other, teams, cur_q):
    _manager_setup(teams, member, ky_peer)
    value = CoreValue.objects.create(name="Own it")
    statement = SuccessStatement.objects.create(person=member, text="Hit the plan")
    rock = Rock.objects.create(quarter=cur_q, team=teams["ky"], title="Cross-train", owner=member)
    mgr = as_user(ky_peer, teams["ky"])
    r = mgr.post(f"/people/{member.pk}/conversations/new/", {"kind": "quarterly"})
    convo = OneOnOne.objects.get(person=member, kind=OneOnOne.QUARTERLY)
    assert r.url == f"/conversations/{convo.pk}/" and convo.quarter == cur_q and convo.manager == ky_peer
    mgr.post(f"/people/{member.pk}/conversations/new/", {"kind": "quarterly"})
    assert OneOnOne.objects.filter(kind=OneOnOne.QUARTERLY).count() == 1

    for subject, color in ((f"value:{value.pk}", "green"), (f"statement:{statement.pk}", "red"), (f"rock:{rock.pk}", "yellow")):
        assert mgr.post(f"/conversations/{convo.pk}/score/", {"subject": subject, "color": color}, **HTMX).status_code == 200
    mgr.post(f"/conversations/{convo.pk}/score/", {"subject": f"statement:{statement.pk}", "note": "Two missed weeks"}, **HTMX)
    assert convo.color_counts == {"green": 1, "yellow": 1, "red": 1}
    assert ConversationScore.objects.get(statement=statement).note == "Two missed weeks"
    other_statement = SuccessStatement.objects.create(person=other, text="Not theirs")
    assert mgr.post(f"/conversations/{convo.pk}/score/", {"subject": f"statement:{other_statement.pk}", "color": "green"}).status_code == 403

    mgr.post(f"/conversations/{convo.pk}/", {"gets_it": "yes", "wants_it": "yes", "capacity": "no", "highlight": "Solid"}, **HTMX)
    mgr.post(f"/conversations/{convo.pk}/", {"complete": "1"})
    convo.refresh_from_db()
    assert convo.capacity is False and convo.highlight == "Solid" and convo.completed_at and convo.is_struggling

    assert as_user(member, teams["ky"]).get(f"/conversations/{convo.pk}/").status_code == 200
    assert as_user(member, teams["ky"]).post(f"/conversations/{convo.pk}/score/", {"subject": f"value:{value.pk}", "color": "red"}).status_code == 403
    assert as_user(other).get(f"/conversations/{convo.pk}/").status_code == 403


def test_conversation_tracker_counts(as_user, admin, member, ky_peer, teams, cur_q):
    _manager_setup(teams, member, ky_peer)
    OneOnOne.objects.create(person=member, manager=ky_peer, kind=OneOnOne.QUARTERLY, quarter=cur_q, completed_at=timezone.now())
    page = as_user(ky_peer, teams["ky"]).get("/conversations/")
    rows = {r["person"].pk: r for r in page.context["rows"]}
    assert set(rows) == {member.pk, ky_peer.pk} and rows[member.pk]["state"] == "done"
    assert page.context["done"] == 1 and page.context["pct"] == 50
    everyone = as_user(admin, teams["ky"]).get("/conversations/?all=1")
    assert admin.pk in {r["person"].pk for r in everyone.context["rows"]}


# ---------------- Planning sessions ----------------

def test_quarterly_planning_session_flow(as_user, admin, member, other, teams, cur_q):
    c = as_user(admin, teams["company"])
    r = c.post("/planning/start/", {"kind": "quarterly"})
    session = Session.objects.get()
    assert r.url == f"/planning/{session.pk}/" and session.next_quarter.start_date == cur_q.end_date + dt.timedelta(days=1)
    for key in session.section_keys:
        assert c.get(f"/planning/{session.pk}/?s={key}").status_code == 200
    assert as_user(other, teams["lr"]).post(f"/planning/{session.pk}/items/", {"section": "segue", "kind": "best_news", "text": "x"}).status_code == 403

    c.post(f"/planning/{session.pk}/items/", {"section": "segue", "kind": "not_working", "text": "Changeovers too slow"})
    item = SessionItem.objects.get()
    c.post(f"/planning/items/{item.pk}/", {"action": "issue"})
    assert Issue.objects.filter(title="Changeovers too slow", team=teams["company"]).exists()

    c.post(f"/planning/{session.pk}/rocks/", {"title": "Portal live", "company": "1", "owner": admin.pk})
    rock = Rock.objects.get(title="Portal live")
    assert rock.quarter == session.next_quarter and rock.is_company

    r = c.post(f"/planning/{session.pk}/update/", {"section": "segue", "notes": "Great energy"}, **HTMX)
    assert r.status_code == 204
    c.post(f"/planning/{session.pk}/update/", {"one_year_goals": "Second plant"}, **HTMX)
    c.post(f"/planning/{session.pk}/todos/", {"title": "Send recap", "owner": admin.pk})
    c.post(f"/planning/{session.pk}/rate/", {"rating": "9"})
    r = c.post(f"/planning/{session.pk}/conclude/")
    session.refresh_from_db()
    assert session.is_concluded and session.average_rating == 9 and r.url == f"/planning/{session.pk}/recap/"
    recap = c.get(f"/planning/{session.pk}/recap/").content.decode()
    assert "Changeovers too slow" in recap and "Portal live" in recap and "Send recap" in recap and "Great energy" in recap
    from vision.models import VTO
    assert VTO.load().one_year_goals == "Second plant"


def test_only_admins_edit_the_vto_from_a_session(as_user, member, teams, cur_q):
    session = Session.objects.create(kind="annual", team=teams["ky"], quarter=cur_q)
    assert as_user(member, teams["ky"]).post(f"/planning/{session.pk}/update/", {"one_year_goals": "x"}, **HTMX).status_code == 403


# ---------------- L10 + V/TO ----------------

def test_l10_cascading_messages_autosave_and_recap(as_user, admin, teams, cur_q):
    from meetings.models import Meeting

    m = Meeting.objects.create(team=teams["company"], quarter=cur_q, facilitator=admin)
    m.attendees.add(admin)
    c = as_user(admin, teams["company"])
    r = c.post(f"/meetings/{m.pk}/update/", {"cascading_messages": "Plant closed Friday", "autosave": "1"}, **HTMX)
    assert r.status_code == 204
    assert "Plant closed Friday" in c.get(f"/meetings/{m.pk}/recap/").content.decode()
    from django.core import mail

    c.post(f"/meetings/{m.pk}/recap/send/")
    assert mail.outbox and "CASCADING MESSAGES" in mail.outbox[0].body


def test_core_processes_admin_only(as_user, admin, member):
    assert as_user(member).post("/vto/processes/", {"name": "Sales"}).status_code == 403
    as_user(admin).post("/vto/processes/", {"name": "Sales", "steps": "Qualify\nClose", "documented": "1"})
    p = CoreProcess.objects.get()
    assert p.step_list == ["Qualify", "Close"] and p.documented and not p.followed_by_all
    assert b"Core processes" in as_user(member).get("/vto/").content


# ---------------- Demo data + assets ----------------

def test_seed_demo_only_runs_on_an_empty_database(db):
    call_command("seed_demo")
    assert Seat.objects.filter(status=Seat.OPEN).exists() and RockUpdate.objects.exists() and Session.objects.exists()
    with pytest.raises(CommandError):
        call_command("seed_demo")


def test_compiled_tailwind_is_committed_and_used(client, admin):
    path = os.path.join(settings.BASE_DIR, "static", "css", "app.css")
    css = open(path).read()
    assert ".bg-bolt" in css and "has-\\[\\:checked\\]" in css
    client.force_login(admin)
    html = client.get("/").content.decode()
    assert "css/app.css" in html and "cdn.tailwindcss.com" not in html
