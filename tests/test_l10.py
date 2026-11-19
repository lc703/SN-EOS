import datetime as dt
import json

import pytest
from django.test import Client
from django.utils import timezone

from api.models import ApiToken
from meetings.models import CascadingMessage, Headline, Meeting, MeetingRating
from rocks.models import Rock, RockUpdate

pytestmark = pytest.mark.django_db

HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def company_meeting(teams, admin, quarter):
    m = Meeting.objects.create(team=teams["company"], quarter=quarter, facilitator=admin, started_at=timezone.now() - dt.timedelta(hours=1))
    m.attendees.set([admin])
    return m


@pytest.fixture
def ky_meeting(teams, member, ky_peer, quarter):
    m = Meeting.objects.create(team=teams["ky"], quarter=quarter, facilitator=member)
    m.attendees.set([member, ky_peer])
    return m


def test_cascading_message_reaches_recipient_headlines(as_user, teams, admin, member, company_meeting, ky_meeting):
    c = as_user(admin, teams["company"])
    resp = c.post(f"/meetings/{company_meeting.pk}/cascades/", {"text": "Budgets out Friday", "to_teams": [teams["ky"].pk]}, **HX)
    assert resp.status_code == 204
    assert "meetingChanged" in json.loads(resp["HX-Trigger"])
    msg = CascadingMessage.objects.get()
    assert not msg.to_everyone and list(msg.to_teams.all()) == [teams["ky"]]

    ky = as_user(member, teams["ky"]).get(f"/meetings/{ky_meeting.pk}/?s=headlines").content.decode()
    assert "Cascading messages for Kentucky" in ky and "Budgets out Friday" in ky
    lr = Meeting.objects.create(team=teams["lr"], quarter=company_meeting.quarter)
    assert "Budgets out Friday" not in as_user(admin).get(f"/meetings/{lr.pk}/?s=headlines").content.decode()


def test_cascade_to_everyone_and_validation(as_user, teams, admin, company_meeting):
    c = as_user(admin, teams["company"])
    assert c.post(f"/meetings/{company_meeting.pk}/cascades/", {"text": "No recipients"}, **HX).status_code == 422
    c.post(f"/meetings/{company_meeting.pk}/cascades/", {"text": "All hands Friday", "to_everyone": "1"}, **HX)
    msg = CascadingMessage.objects.get()
    assert msg.to_everyone
    conclude = c.get(f"/meetings/{company_meeting.pk}/?s=conclude").content.decode()
    assert "All hands Friday" in conclude
    recap = c.get(f"/meetings/{company_meeting.pk}/recap/").content.decode()
    assert "All hands Friday" in recap and "Everyone" in recap
    c.post(f"/cascades/{msg.pk}/delete/", **HX)
    assert not CascadingMessage.objects.exists()


def test_outsider_cannot_cascade(as_user, teams, other, company_meeting):
    resp = as_user(other, teams["lr"]).post(f"/meetings/{company_meeting.pk}/cascades/", {"text": "x", "to_everyone": "1"}, **HX)
    assert resp.status_code == 403


def test_htmx_rating_and_headline(as_user, teams, member, ky_peer, ky_meeting):
    c = as_user(member, teams["ky"])
    resp = c.post(f"/meetings/{ky_meeting.pk}/rate/", {"user": member.pk, "rating": "9"}, **HX)
    assert resp.status_code == 204
    assert MeetingRating.objects.get(user=member).rating == 9
    page = c.get(f"/meetings/{ky_meeting.pk}/?s=conclude").content.decode()
    assert 'class="rate-btn on"' in page
    c.post(f"/meetings/{ky_meeting.pk}/headlines/", {"kind": "employee", "text": "Night shift fully staffed"}, **HX)
    assert Headline.objects.get().meeting == ky_meeting


def test_segue_autosave_and_attendees(as_user, teams, member, ky_peer, ky_meeting):
    c = as_user(member, teams["ky"])
    assert c.post(f"/meetings/{ky_meeting.pk}/update/", {"segue_notes": "Good harvest"}, **HX).status_code == 204
    c.post(f"/meetings/{ky_meeting.pk}/update/", {"attendees_present": "1", "attendees": [member.pk]}, **HX)
    ky_meeting.refresh_from_db()
    assert ky_meeting.segue_notes == "Good harvest"
    assert list(ky_meeting.attendees.all()) == [member]


def test_rock_review_shows_latest_update_and_recovery_plan(as_user, teams, member, ky_meeting, quarter):
    rock = Rock.objects.create(team=teams["ky"], quarter=quarter, title="New die", owner=member)
    RockUpdate.objects.create(rock=rock, week_start=quarter.start_date, rag="red", note="Vendor slipped", recovery_plan="Expedite shipping")
    page = as_user(member, teams["ky"]).get(f"/meetings/{ky_meeting.pk}/?s=rocks").content.decode()
    assert "Vendor slipped" in page and "Expedite shipping" in page
    assert "Drop to Issues" in page


def test_section_badges_and_navigation(as_user, teams, member, ky_meeting):
    page = as_user(member, teams["ky"]).get(f"/meetings/{ky_meeting.pk}/?s=segue").content.decode()
    assert "data-shortcut-next" in page and "Section 1" in page


def test_meetings_list_rating_chart(as_user, teams, admin, quarter):
    for i, score in enumerate([7, 9]):
        m = Meeting.objects.create(team=teams["company"], quarter=quarter, date=quarter.start_date + dt.timedelta(weeks=i), concluded_at=timezone.now())
        MeetingRating.objects.create(meeting=m, user=admin, rating=score)
    page = as_user(admin, teams["company"]).get("/meetings/").content.decode()
    assert "<svg" in page and "8.0" in page


def test_mcp_add_cascading_message(teams, member, ky_meeting):
    _, raw = ApiToken.issue(member, "Claude")
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "add_cascading_message", "arguments": {"meeting_id": ky_meeting.pk, "text": "Die installed", "to_teams": ["Le Roy"]}}}
    res = Client().post("/mcp", data=json.dumps(msg), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {raw}").json()
    assert res["result"]["structuredContent"]["to_teams"] == [teams["lr"].slug]
    assert CascadingMessage.objects.get().author == member
