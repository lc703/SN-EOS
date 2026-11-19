import json

import pytest

from rocks.models import Rock
from vision.models import VTO, Goal

pytestmark = pytest.mark.django_db

HX = {"HTTP_HX_REQUEST": "true"}


def test_vto_shows_goals_with_linked_rocks_and_strategy(as_user, teams, admin, member, quarter):
    goal = Goal.objects.create(title="World-class plant reliability", strategy="PM at every mill", tactics="PM software\nSpares list")
    Rock.objects.create(team=teams["company"], quarter=quarter, is_company=True, title="Cut downtime 25%", owner=member, goal=goal)
    vto = VTO.load()
    vto.legacy = {"strategy_house": {"major_business_challenge": "Grow without a fourth mill", "targets": [{"value": "$26M", "label": "Revenue"}]}}
    vto.save()
    html = as_user(member).get("/vto/").content.decode()
    assert "World-class plant reliability" in html and "PM software" in html and "Cut downtime 25%" in html
    assert "Grow without a fourth mill" in html and "$26M" in html


def test_admin_adds_edits_and_removes_goal(as_user, teams, admin):
    c = as_user(admin)
    assert c.get("/vto/goals/new/", **HX).status_code == 200
    resp = c.post("/vto/goals/new/", {"title": "Build the bench", "tactics": "QCs"}, **HX)
    assert "vtoChanged" in json.loads(resp["HX-Trigger"])
    g = Goal.objects.get()
    c.post(f"/vto/goals/{g.pk}/", {"title": "Build the leadership bench", "autosave": "1"}, **HX)
    g.refresh_from_db()
    assert g.title == "Build the leadership bench"
    assert c.post(f"/vto/goals/{g.pk}/", {"title": "", "autosave": "1"}, **HX).status_code == 422
    c.post(f"/vto/goals/{g.pk}/", {"delete": "1"}, **HX)
    assert not Goal.objects.exists()


def test_members_cannot_edit_goals(as_user, teams, member):
    assert as_user(member).post("/vto/goals/new/", {"title": "x"}, **HX).status_code == 403
