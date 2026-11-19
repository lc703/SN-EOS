"""Someone else's 90: the personal dashboard, with the same privacy as the rest of the app."""

import json

import pytest
from django.test import Client
from django.utils import timezone

from api.models import ApiToken
from issues.models import Issue
from meetings.models import Meeting
from people.models import OneOnOne, PeopleReview
from rocks.models import Rock
from scorecard.models import Measurable
from tests.test_api import bearer
from todos.models import Todo
from vision.models import Seat

pytestmark = pytest.mark.django_db


SECRET = "SECRET-COACHING-NOTE"
GWC = "SECRET-GWC-NOTE"


def _world(member, teams, quarter):
    rock = Rock.objects.create(quarter=quarter, team=teams["ky"], title="Ship the labels", owner=member)
    measurable = Measurable.objects.create(team=teams["ky"], title="Cases packed", owner=member, goal=100)
    issue = Issue.objects.create(team=teams["ky"], title="Label printer jams", owner=member)
    public = Todo.objects.create(team=teams["ky"], title="Order labels", owner=member)
    private = Todo.objects.create(team=teams["ky"], title="Kim secret task", owner=member, is_private=True)
    seat = Seat.objects.create(team=teams["ky"], title="Plant Lead", person=member)
    meeting = Meeting.objects.create(team=teams["ky"], quarter=quarter, date=timezone.localdate())
    OneOnOne.objects.create(person=member, highlight=SECRET, notes="keep this off the dashboard")
    PeopleReview.objects.create(person=member, notes=GWC, gets_it=True, wants_it=True, capacity=False)
    return {
        "rock": rock, "measurable": measurable, "issue": issue,
        "public": public, "private": private, "seat": seat, "meeting": meeting,
    }


def test_person_dashboard_shows_their_90_and_hides_private_people_data(member, other, teams, quarter, as_user):
    world = _world(member, teams, quarter)
    page = as_user(other).get(f"/people/{member.pk}/dashboard/")
    assert page.status_code == 200
    body = page.content.decode()
    assert "Kim Member's dashboard" in body
    assert 'href="/"' in body and "My dashboard" in body
    assert "Order labels" in body
    assert "Kim secret task" not in body
    assert "Ship the labels" in body
    assert "13-week status" in body
    assert "Cases packed" in body
    assert ">Trend<" in body
    assert "Label printer jams" in body
    assert "Plant Lead" in body
    assert f'/meetings/{world["meeting"].pk}/' in body
    assert SECRET not in body and GWC not in body
    # Someone who can't edit Kim's work gets a read-only to-do, rock and scorecard.
    assert f'/todos/{world["public"].pk}/toggle/' not in body
    assert f'/rocks/{world["rock"].pk}/status/' not in body
    assert f'/scorecard/{world["measurable"].pk}/cell/' not in body
    assert "disabled" in body


def test_owner_and_admin_keep_their_edit_rights(member, admin, teams, quarter, as_user):
    world = _world(member, teams, quarter)
    own = as_user(member).get("/").content.decode()
    assert "Hi Kim, here’s your 90." in own
    assert "Kim secret task" in own
    assert f'/todos/{world["public"].pk}/toggle/' in own
    assert f'/rocks/{world["rock"].pk}/status/' in own
    assert f'/scorecard/{world["measurable"].pk}/cell/' in own

    managed = as_user(admin).get(f"/people/{member.pk}/dashboard/").content.decode()
    assert "Kim Member's dashboard" in managed
    assert "Kim secret task" not in managed
    assert SECRET not in managed and GWC not in managed
    assert f'/todos/{world["public"].pk}/toggle/' in managed
    assert f'/rocks/{world["rock"].pk}/status/' in managed
    assert f'/scorecard/{world["measurable"].pk}/cell/' in managed


def test_a_teammate_can_still_edit_a_public_todo(member, ky_peer, teams, quarter, as_user):
    public = Todo.objects.create(team=teams["ky"], title="Shared line task", owner=member)
    body = as_user(ky_peer).get(f"/people/{member.pk}/dashboard/").content.decode()
    assert "Shared line task" in body
    assert f'/todos/{public.pk}/toggle/' in body


def test_private_todo_stays_with_the_owner_and_its_creator(member, other, admin, teams, quarter, as_user):
    Todo.objects.create(
        team=teams["ky"], title="Assigned quietly", owner=member, is_private=True, created_by=other
    )
    assert "Assigned quietly" in as_user(other).get(f"/people/{member.pk}/dashboard/").content.decode()
    assert "Assigned quietly" in as_user(member).get("/").content.decode()
    assert "Assigned quietly" not in as_user(admin).get(f"/people/{member.pk}/dashboard/").content.decode()


def test_person_query_redirects_to_the_shareable_url(member, other, as_user):
    gone = as_user(other).get(f"/?person={member.pk}")
    assert gone.status_code == 302
    assert gone.url == f"/people/{member.pk}/dashboard/"
    mine = as_user(member).get(f"/?person={member.pk}")
    assert mine.status_code == 302 and mine.url == "/"
    assert as_user(member).get(f"/people/{member.pk}/dashboard/").status_code == 302
    assert as_user(other).get("/?person=nope").status_code == 404
    assert as_user(other).get("/people/999999/dashboard/").status_code == 404


def test_anonymous_cannot_open_a_dashboard(member):
    response = Client().get(f"/people/{member.pk}/dashboard/")
    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


def test_picker_groups_people_and_links_from_the_places_you_already_look(member, other, teams, as_user):
    Seat.objects.create(team=teams["ky"], title="Plant Lead", person=member)
    home = as_user(other).get("/")
    assert home.status_code == 200
    body = home.content.decode()
    assert "View someone’s 90" in body
    assert "Kentucky" in body and "Kim Member" in body
    assert f"/people/{member.pk}/dashboard/" in body  # picker JSON and the command palette

    people = as_user(other).get("/people/?all=1").content.decode()
    assert f'href="/people/{member.pk}/dashboard/"' in people

    profile = as_user(other).get(f"/people/{member.pk}/").content.decode()
    assert f'href="/people/{member.pk}/dashboard/"' in profile

    seat = Seat.objects.get(person=member)
    panel = as_user(other).get(f"/chart/seats/{seat.pk}/panel/").content.decode()
    assert f"/people/{member.pk}/dashboard/" in panel


def test_my_90_person_follows_the_same_privacy(member, other, teams, quarter):
    Todo.objects.create(team=teams["ky"], title="Kim public", owner=member)
    Todo.objects.create(team=teams["ky"], title="Kim secret", owner=member, is_private=True)
    OneOnOne.objects.create(person=member, highlight=SECRET)
    Rock.objects.create(quarter=quarter, team=teams["ky"], title="Ship the labels", owner=member)
    Seat.objects.create(team=teams["ky"], title="Plant Lead", person=member)

    _, raw = ApiToken.issue(other, "t")
    data = Client().get("/api/v1/my90", {"person": member.email}, **bearer(raw)).json()["data"]
    titles = [t["title"] for t in data["todos"]]
    assert titles == ["Kim public"]
    blob = json.dumps(data)
    assert SECRET not in blob
    assert data["person"]["email"] == member.email
    assert data["rocks"][0]["title"] == "Ship the labels"
    assert data["seats"][0]["title"] == "Plant Lead"

    _, mine = ApiToken.issue(member, "me")
    own = Client().get("/api/v1/my90", **bearer(mine)).json()["data"]
    assert {t["title"] for t in own["todos"]} == {"Kim public", "Kim secret"}
