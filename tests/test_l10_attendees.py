"""An L10 shows only items owned by the people in the meeting (its attendees); the rest are counted and one
click away. Pages outside the L10 are unchanged."""

import re

import pytest
from django.utils import timezone

from issues.models import Issue
from meetings.models import Headline, Meeting
from rocks.models import Rock
from todos.models import Todo
from tests.conftest import client_for
from tests.test_rollup import all_teams, cur_q, get, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


def l10(team, cur_q, *attendees, facilitator=None):
    m = Meeting.objects.create(team=team, quarter=cur_q, date=timezone.localdate(), facilitator=facilitator)
    m.attendees.set(attendees)
    return m


def page(user, meeting, section, extra=""):
    return client_for(user).get(f"/meetings/{meeting.pk}/?s={section}{extra}").content.decode()


SECTIONS = [("ids", "Issue"), ("todos", "Todo"), ("rocks", "Rock")]


@pytest.mark.parametrize("section,needle", SECTIONS)
def test_only_attendees_items_show_in_a_site_l10_including_the_company_group(member, admin, all_teams, world, cur_q, section, needle):
    meeting = l10(all_teams["ky"], cur_q, member, facilitator=member)  # Kim is here; Ada (owns the Company items) is not
    body = page(member, meeting, section)
    assert f"{needle} ky" in body
    assert f"{needle} company" not in body and "from Company, not Kentucky" not in body
    assert f"{needle} lr" not in body and f"{needle} mabel" not in body
    assert re.search(r"<strong>1</strong> item hidden: owners not in this meeting", body)
    meeting.attendees.add(admin)
    body = page(member, meeting, section)
    assert body.index(f"{needle} ky") < body.index("from Company, not Kentucky") < body.index(f"{needle} company")
    assert "hidden: owners not in this meeting" not in body


@pytest.mark.parametrize("section,needle", SECTIONS)
def test_show_all_reveals_the_hidden_items_and_can_be_turned_off(member, admin, all_teams, world, cur_q, section, needle):
    meeting = l10(all_teams["ky"], cur_q, member, facilitator=member)
    hidden = page(member, meeting, section)
    assert f'href="?s={section}&all=1"' in hidden
    shown = page(member, meeting, section, "&all=1")
    assert f"{needle} company" in shown and f"{needle} ky" in shown
    assert f"{needle} lr" not in shown  # other sites are never shown, even with show all
    assert "shown for people not in this meeting" in shown and f'href="?s={section}"' in shown


def test_scorecard_shows_only_attendee_owned_measurables(member, admin, all_teams, world, cur_q):
    meeting = l10(all_teams["ky"], cur_q, member, facilitator=member)
    ids = lambda body: re.findall(r'id="m-(\d+)"', body)
    assert ids(page(member, meeting, "scorecard")) == [str(world["oee"]["kentucky"].pk)]
    meeting.attendees.add(admin)
    assert ids(page(member, meeting, "scorecard")) == [str(world[k].pk) for k in ("pipe", "leads")] + [str(world["oee"]["kentucky"].pk)]
    assert len(ids(page(member, l10(all_teams["ky"], cur_q, member), "scorecard", "&all=1"))) == 3


def test_unowned_items_and_an_empty_roster_still_show(member, admin, all_teams, world, cur_q):
    Issue.objects.create(team=all_teams["ky"], title="Nobody owns this", owner=None)
    meeting = l10(all_teams["ky"], cur_q, member, facilitator=member)
    assert "Nobody owns this" in page(member, meeting, "ids")
    empty = l10(all_teams["ky"], cur_q, facilitator=member)
    body = page(member, empty, "ids")
    assert "Issue ky" in body and "No attendees yet" in body and "hidden:" not in body


def test_headlines_are_not_filtered(member, other, all_teams, world, cur_q):
    Headline.objects.create(team=all_teams["ky"], text="From Lee", author=other)
    meeting = l10(all_teams["ky"], cur_q, member)
    assert "From Lee" in page(member, meeting, "headlines")


def test_meeting_start_roster_is_the_teams_members_plus_whoever_started_it(admin, member, ky_peer, other, all_teams, world, cur_q):
    c = client_for(admin, all_teams["ky"])
    r = c.post("/meetings/start/")
    meeting = Meeting.objects.get(pk=int(r["Location"].strip("/").split("/")[-1]))
    assert set(meeting.attendees.all()) == {member, ky_peer, admin}  # Kentucky's members and Ada, who started it
    lead = client_for(admin, all_teams["company"]).post("/meetings/start/")
    company = Meeting.objects.get(pk=int(lead["Location"].strip("/").split("/")[-1]))
    assert set(company.attendees.all()) == {admin}  # Company's members; Kentucky's people are not in unless added


def test_company_l10_hides_site_items_until_their_owners_are_added(admin, member, all_teams, world, cur_q):
    meeting = l10(all_teams["company"], cur_q, admin, facilitator=admin)
    body = page(admin, meeting, "ids")
    assert "Issue company" in body and "Issue mabel" in body  # Ada owns these
    assert "Issue ky" not in body and "Issue lr" not in body
    c = client_for(admin)
    c.post(f"/meetings/{meeting.pk}/update/", {"add_attendee": member.pk, "next": f"/meetings/{meeting.pk}/?s=segue"})
    assert member in meeting.attendees.all()
    body = page(admin, meeting, "ids")
    assert "Issue ky" in body and "Issue lr" not in body
    assert all(f"Issue {k}" in page(admin, meeting, "ids", "&all=1") for k in ("company", "ky", "lr", "mabel"))


def test_segue_checklist_lets_the_facilitator_add_people_outside_the_team(admin, member, other, all_teams, world, cur_q):
    meeting = l10(all_teams["ky"], cur_q, member, facilitator=member)
    body = page(member, meeting, "segue")
    assert 'name="add_attendee"' in body and f'<option value="{other.pk}">' in body
    c = client_for(member)
    c.post(f"/meetings/{meeting.pk}/update/", {"add_attendee": other.pk, "next": "/"})
    c.post(f"/meetings/{meeting.pk}/update/", {"add_attendee": "junk", "next": "/"})
    assert set(meeting.attendees.all()) == {member, other}
    c.post(f"/meetings/{meeting.pk}/update/", {"attendees_present": 1, "attendees": [member.pk], "next": "/"})
    assert set(meeting.attendees.all()) == {member}


def test_items_made_in_the_meeting_for_a_non_attendee_are_created_but_hidden_with_a_note(member, ky_peer, all_teams, world, cur_q):
    meeting = l10(all_teams["ky"], cur_q, member, facilitator=member)
    c = client_for(member)
    c.post("/issues/new/", {"title": "For Pat", "horizon": "short", "team": all_teams["ky"].pk, "owner": ky_peer.pk, "meeting": meeting.pk})
    c.post("/todos/new/", {"title": "Pat to-do", "owner": ky_peer.pk, "due_date": timezone.localdate().isoformat(), "meeting": meeting.pk})
    issue, todo = Issue.objects.get(title="For Pat"), Todo.objects.get(title="Pat to-do")
    assert issue.owner == ky_peer and todo.owner == ky_peer and todo.meeting == meeting
    ids = page(member, meeting, "ids")
    assert "For Pat" not in ids and re.search(r"<strong>\d+</strong> items? hidden: owners not in this meeting", ids)
    assert "For Pat" in page(member, meeting, "ids", "&all=1")
    done = page(member, meeting, "conclude")
    assert "Pat to-do" not in done and "hidden: owners not in this meeting" in done
    assert "Pat to-do" in page(member, meeting, "conclude", "&all=1")


def test_conclude_recap_shows_only_attendee_items_but_the_printed_recap_is_the_full_record(member, ky_peer, all_teams, world, cur_q):
    meeting = l10(all_teams["ky"], cur_q, member, facilitator=member)
    Todo.objects.create(team=all_teams["ky"], title="Kim to-do", owner=member, meeting=meeting, created_by=member)
    Todo.objects.create(team=all_teams["ky"], title="Pat to-do", owner=ky_peer, meeting=meeting, created_by=member)
    conclude = page(member, meeting, "conclude")
    assert "Kim to-do" in conclude and "Pat to-do" not in conclude
    recap = client_for(member).get(f"/meetings/{meeting.pk}/recap/").content.decode()
    assert "Kim to-do" in recap and "Pat to-do" in recap


def test_rail_links_keep_show_all(member, all_teams, world, cur_q):
    meeting = l10(all_teams["ky"], cur_q, member, facilitator=member)
    assert 'href="?s=todos&all=1"' in page(member, meeting, "ids", "&all=1")
    assert 'href="?s=todos"' in page(member, meeting, "ids")


def test_pages_outside_the_l10_are_unchanged(member, admin, ky_peer, all_teams, world, cur_q):
    l10(all_teams["ky"], cur_q, member, facilitator=member)  # a running meeting does not affect the lists
    Issue.objects.create(team=all_teams["ky"], title="Pats issue", owner=ky_peer)
    for path, mine, company in (("/issues/", "Issue ky", "Issue company"), ("/todos/", "Todo ky", "Todo company"), ("/rocks/", "Rock ky", "Rock company")):
        body = get(member, path, all_teams["ky"]).content.decode()
        assert mine in body and company in body and "hidden: owners not in this meeting" not in body
    assert "Pats issue" in get(member, "/issues/", all_teams["ky"]).content.decode()
