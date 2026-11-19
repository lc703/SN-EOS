import datetime as dt

import pytest

from core.models import Quarter
from issues.models import Issue
from planning.models import Session, SessionItem, SessionRating
from rocks.models import Rock
from vision.models import Goal

pytestmark = pytest.mark.django_db

HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def next_q(db):
    return Quarter.objects.create(name="Q1 2027", start_date=dt.date(2027, 1, 1), end_date=dt.date(2027, 3, 31))


def test_create_session_plans_next_quarter(as_user, teams, admin, quarter, next_q):
    c = as_user(admin, teams["company"])
    r = c.post("/sessions/new/", {"kind": "quarterly"})
    s = Session.objects.get()
    assert r.url == f"/sessions/{s.pk}/"
    assert s.quarter == next_q and s.facilitator == admin
    assert admin in s.attendees.all()


def test_every_agenda_step_renders(as_user, teams, admin, quarter, next_q):
    c = as_user(admin, teams["company"])
    for kind in ("quarterly", "annual"):
        s = Session.objects.create(team=teams["company"], quarter=next_q, kind=kind, facilitator=admin)
        for step in s.step_keys:
            assert c.get(f"/sessions/{s.pk}/?s={step}").status_code == 200, (kind, step)
        s.refresh_from_db()
        assert s.current_step == s.step_keys[-1]


def test_brainstorm_to_rock_issue_and_goal(as_user, teams, admin, member, quarter, next_q):
    s = Session.objects.create(team=teams["company"], quarter=next_q, kind=Session.ANNUAL, facilitator=admin)
    c = as_user(admin, teams["company"])
    assert c.post(f"/sessions/{s.pk}/items/", {"step": "rocks", "kind": "rock_idea", "text": "Dealer portal pilot"}, **HX).status_code == 204
    idea = SessionItem.objects.get()
    c.post(f"/session-items/{idea.pk}/", {"action": "rock", "owner": member.pk}, **HX)
    rock = Rock.objects.get()
    assert rock.quarter == next_q and rock.owner == member and rock.is_company
    idea.refresh_from_db()
    assert idea.rag == "rock"

    c.post(f"/sessions/{s.pk}/items/", {"step": "swot", "kind": "swot_threat", "text": "Commodity swings"}, **HX)
    threat = SessionItem.objects.get(kind="swot_threat")
    c.post(f"/session-items/{threat.pk}/", {"action": "issue"}, **HX)
    assert Issue.objects.get().horizon == Issue.LONG

    c.post(f"/sessions/{s.pk}/goals/", {"title": "Four mills on one system"}, **HX)
    assert Goal.objects.filter(title="Four mills on one system").exists()
    page = c.get(f"/sessions/{s.pk}/?s=rocks").content.decode()
    assert "Dealer portal pilot" in page and "Q1 2027 Rocks" in page


def test_item_validation_and_delete(as_user, teams, admin, quarter, next_q):
    s = Session.objects.create(team=teams["company"], quarter=next_q, facilitator=admin)
    c = as_user(admin, teams["company"])
    c.post(f"/sessions/{s.pk}/items/", {"step": "segue", "kind": "swot_threat", "text": "wrong bucket"}, **HX)
    assert not SessionItem.objects.exists()
    c.post(f"/sessions/{s.pk}/items/", {"step": "segue", "kind": "news", "text": "Record harvest"}, **HX)
    item = SessionItem.objects.get()
    c.post(f"/session-items/{item.pk}/", {"action": "delete"}, **HX)
    assert not SessionItem.objects.exists()


def test_rate_and_conclude(as_user, teams, admin, member, quarter, next_q):
    s = Session.objects.create(team=teams["company"], quarter=next_q, facilitator=admin)
    s.attendees.set([admin, member])
    c = as_user(admin, teams["company"])
    c.post(f"/sessions/{s.pk}/rate/", {"user": admin.pk, "rating": "9"}, **HX)
    c.post(f"/sessions/{s.pk}/rate/", {"user": member.pk, "rating": "7"}, **HX)
    assert as_user(member).post(f"/sessions/{s.pk}/rate/", {"user": admin.pk, "rating": "1"}).status_code == 403
    c.post(f"/sessions/{s.pk}/conclude/")
    s.refresh_from_db()
    assert s.is_concluded and s.average_rating == 8.0
    assert SessionRating.objects.count() == 2


def test_outsiders_cannot_edit_session(as_user, teams, admin, other, quarter, next_q):
    s = Session.objects.create(team=teams["company"], quarter=next_q, facilitator=admin)
    c = as_user(other, teams["lr"])
    assert c.post(f"/sessions/{s.pk}/items/", {"step": "segue", "kind": "news", "text": "x"}, **HX).status_code == 403
    assert c.post(f"/sessions/{s.pk}/rocks/", {"title": "x"}, **HX).status_code == 403


def test_review_step_scores_previous_quarter(as_user, teams, admin, member, quarter, next_q):
    Rock.objects.create(team=teams["company"], quarter=quarter, is_company=True, title="Finish budget", owner=member, status=Rock.DONE)
    Rock.objects.create(team=teams["company"], quarter=quarter, is_company=True, title="Hire rep", owner=member)
    s = Session.objects.create(team=teams["company"], quarter=next_q, facilitator=admin)
    html = as_user(admin, teams["company"]).get(f"/sessions/{s.pk}/?s=review").content.decode()
    assert "Finish budget" in html and "Hire rep" in html and "50%" in html
