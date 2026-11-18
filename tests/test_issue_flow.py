import datetime as dt
from decimal import Decimal

import pytest
from django.core import mail

from issues.models import Issue
from meetings.models import Headline, Meeting
from rocks.models import Rock
from scorecard.models import Measurable, ScoreEntry
from todos.models import Todo

pytestmark = pytest.mark.django_db


def test_drop_red_measurable_to_issues(as_user, teams, member, quarter):
    m = Measurable.objects.create(team=teams["ky"], title="OEE", owner=member, unit="percent", goal=Decimal(65))
    ScoreEntry.objects.create(measurable=m, week_start=quarter.weeks()[2], value=Decimal(50))
    c = as_user(member, teams["ky"])
    r = c.post("/issues/drop/", {"kind": "measurable", "id": m.pk}, HTTP_HX_REQUEST="true")
    assert "In Issues" in r.content.decode()
    issue = Issue.objects.get()
    assert issue.source_measurable == m and issue.team == teams["ky"] and issue.is_open
    assert "50%" in issue.title and "≥ 65%" in issue.title
    r = c.post("/issues/drop/", {"kind": "measurable", "id": m.pk}, HTTP_HX_REQUEST="true")
    assert "Already in Issues" in r.content.decode() and Issue.objects.count() == 1


def test_drop_rock_and_headline_from_meeting(as_user, teams, member, quarter):
    meeting = Meeting.objects.create(team=teams["ky"], quarter=quarter, facilitator=member)
    rock = Rock.objects.create(quarter=quarter, team=teams["ky"], title="New line", owner=member, status=Rock.OFF_TRACK)
    h = Headline.objects.create(team=teams["ky"], meeting=meeting, text="Customer X complained", author=member)
    c = as_user(member, teams["ky"])
    c.post("/issues/drop/", {"kind": "rock", "id": rock.pk, "meeting": meeting.pk})
    c.post("/issues/drop/", {"kind": "headline", "id": h.pk, "meeting": meeting.pk})
    titles = set(Issue.objects.values_list("title", flat=True))
    assert titles == {"Rock off track: New line", "Customer headline: Customer X complained"}
    assert set(meeting.raised_issues.values_list("pk", flat=True)) == set(Issue.objects.values_list("pk", flat=True))


def test_ids_solve_creates_todos_and_marks_solved(as_user, teams, member, ky_peer, quarter):
    meeting = Meeting.objects.create(team=teams["ky"], quarter=quarter, facilitator=member)
    issue = Issue.objects.create(team=teams["ky"], title="Changeovers slow", owner=member, priority=1)
    due = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    r = as_user(member, teams["ky"]).post(
        f"/issues/{issue.pk}/solve/",
        {
            "action": "solve",
            "meeting": meeting.pk,
            "resolution": "Standard changeover checklist",
            "todo_title": ["Write checklist", "Train line leads", ""],
            "todo_owner": [member.pk, ky_peer.pk, member.pk],
            "todo_due": [due, "", ""],
        },
    )
    assert r.status_code == 302
    issue.refresh_from_db()
    assert issue.status == Issue.SOLVED and issue.solved_meeting == meeting and issue.resolution == "Standard changeover checklist"
    todos = {t.title: t for t in Todo.objects.all()}
    assert set(todos) == {"Write checklist", "Train line leads"}
    assert todos["Write checklist"].due_date.isoformat() == due
    assert todos["Train line leads"].owner == ky_peer
    assert todos["Train line leads"].due_date == dt.date.today() + dt.timedelta(days=7)
    assert all(t.issue == issue and t.meeting == meeting and t.team == teams["ky"] and not t.is_private for t in todos.values())


def test_save_todos_without_solving(as_user, teams, member):
    issue = Issue.objects.create(team=teams["ky"], title="Hiring", owner=member)
    as_user(member).post(f"/issues/{issue.pk}/solve/", {"action": "todos", "todo_title": ["Post job"], "todo_owner": [member.pk]})
    issue.refresh_from_db()
    assert issue.is_open and issue.todos.count() == 1


def test_priority_endpoint_toggles_and_bumps(as_user, teams, member):
    a = Issue.objects.create(team=teams["ky"], title="A", owner=member)
    b = Issue.objects.create(team=teams["ky"], title="B", owner=member)
    c = as_user(member)
    c.post(f"/issues/{a.pk}/priority/", {"rank": "1"})
    c.post(f"/issues/{b.pk}/priority/", {"rank": "1"})
    a.refresh_from_db(), b.refresh_from_db()
    assert (a.priority, b.priority) == (None, 1)
    c.post(f"/issues/{b.pk}/priority/", {"rank": "1"})
    b.refresh_from_db()
    assert b.priority is None


def test_meeting_conclude_recap_and_ratings(as_user, teams, member, ky_peer, quarter):
    c = as_user(member, teams["ky"])
    r = c.post("/meetings/start/")
    meeting = Meeting.objects.get()
    assert r.url == f"/meetings/{meeting.pk}/"
    assert set(meeting.attendees.all()) == {member, ky_peer}

    for s in ["segue", "scorecard", "rocks", "headlines", "todos", "ids", "conclude"]:
        assert c.get(f"/meetings/{meeting.pk}/?s={s}").status_code == 200
    meeting.refresh_from_db()
    assert meeting.current_section == "conclude"  # facilitator position follows the facilitator

    c.post("/todos/new/", {"title": "Order spare parts", "owner": ky_peer.pk, "due_date": "2026-01-01", "meeting": meeting.pk})
    issue = Issue.objects.create(team=teams["ky"], title="Spare parts", owner=member)
    c.post(f"/issues/{issue.pk}/solve/", {"action": "solve", "meeting": meeting.pk})
    c.post(f"/meetings/{meeting.pk}/rate/", {"user": member.pk, "rating": "8"})
    c.post(f"/meetings/{meeting.pk}/rate/", {"user": ky_peer.pk, "rating": "10"})  # facilitator enters for the room
    assert as_user(ky_peer).post(f"/meetings/{meeting.pk}/rate/", {"user": member.pk, "rating": "1"}).status_code == 403
    c.post(f"/meetings/{meeting.pk}/conclude/")
    meeting.refresh_from_db()
    assert meeting.is_concluded and meeting.average_rating == 9.0

    recap = c.get(f"/meetings/{meeting.pk}/recap/").content.decode()
    assert "Order spare parts" in recap and "Spare parts" in recap and "9.0" in recap
    c.post(f"/meetings/{meeting.pk}/recap/send/")
    assert len(mail.outbox) == 1 and "Order spare parts" in mail.outbox[0].body
    assert set(mail.outbox[0].to) == {member.email, ky_peer.email}


def test_non_facilitator_viewing_does_not_move_the_room(as_user, teams, member, ky_peer, quarter):
    meeting = Meeting.objects.create(team=teams["ky"], quarter=quarter, facilitator=member, current_section="rocks")
    as_user(ky_peer).get(f"/meetings/{meeting.pk}/?s=ids")
    meeting.refresh_from_db()
    assert meeting.current_section == "rocks"
    banner = as_user(ky_peer).get(f"/meetings/{meeting.pk}/where/?s=ids").content.decode()
    assert "Rock Review" in banner
