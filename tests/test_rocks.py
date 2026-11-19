import json

import pytest

from core.models import monday_of
from rocks.models import Milestone, Rock, RockUpdate

pytestmark = pytest.mark.django_db

HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def rock(teams, member, quarter):
    return Rock.objects.create(team=teams["ky"], quarter=quarter, title="New pellet die", owner=member)


def test_rocks_page_shows_strip_and_update_prompt(as_user, teams, member, rock):
    html = as_user(member, teams["ky"]).get("/rocks/").content.decode()
    assert "New pellet die" in html
    assert 'class="strip' in html
    assert "update" in html.lower()


def test_weekly_update_panel_and_green_update(as_user, teams, member, rock):
    c = as_user(member, teams["ky"])
    panel = c.get(f"/rocks/{rock.pk}/update/", **HX)
    assert panel.status_code == 200
    assert 'name="rag"' in panel.content.decode()
    resp = c.post(f"/rocks/{rock.pk}/update/", {"rag": "green", "note": "Die installed"}, **HX)
    assert resp.status_code == 200
    trigger = json.loads(resp["HX-Trigger"])
    assert "rocksChanged" in trigger and "closePanel" in trigger
    u = RockUpdate.objects.get(rock=rock)
    assert u.rag == "green" and u.note == "Die installed" and u.author == member


def test_red_update_requires_recovery_plan(as_user, teams, member, rock):
    c = as_user(member, teams["ky"])
    resp = c.post(f"/rocks/{rock.pk}/update/", {"rag": "red", "note": "Vendor slipped"}, **HX)
    assert "recovery plan" in resp.content.decode()
    assert not RockUpdate.objects.exists()
    c.post(f"/rocks/{rock.pk}/update/", {"rag": "red", "note": "Vendor slipped", "recovery_plan": "Expedite"}, **HX)
    rock.refresh_from_db()
    assert rock.status == Rock.OFF_TRACK
    assert rock.rag == "red"


def test_update_same_week_overwrites(as_user, teams, member, rock):
    c = as_user(member, teams["ky"])
    c.post(f"/rocks/{rock.pk}/update/", {"rag": "yellow"}, **HX)
    c.post(f"/rocks/{rock.pk}/update/", {"rag": "green"}, **HX)
    assert RockUpdate.objects.filter(rock=rock).count() == 1
    assert RockUpdate.objects.get(rock=rock).week_start == monday_of(RockUpdate.objects.get(rock=rock).week_start)


def test_other_team_member_cannot_post_update(as_user, teams, other, rock):
    resp = as_user(other, teams["lr"]).post(f"/rocks/{rock.pk}/update/", {"rag": "green"}, **HX)
    assert resp.status_code == 403
    assert not RockUpdate.objects.exists()


def test_new_rock_panel_creates_rock(as_user, teams, member, quarter):
    c = as_user(member, teams["ky"])
    assert c.get("/rocks/new/", **HX).status_code == 200
    resp = c.post("/rocks/new/", {"title": "Cross-train batching", "owner": member.pk}, **HX)
    assert "rocksChanged" in json.loads(resp["HX-Trigger"])
    r = Rock.objects.get(title="Cross-train batching")
    assert r.team == teams["ky"] and r.quarter == quarter


def test_new_rock_invalid_rerenders_panel(as_user, teams, member, quarter):
    resp = as_user(member, teams["ky"]).post("/rocks/new/", {"title": ""}, **HX)
    assert resp.status_code == 200
    assert not Rock.objects.exists()


def test_milestones_add_toggle_reorder_delete(as_user, teams, member, rock):
    c = as_user(member, teams["ky"])
    resp = c.post(f"/rocks/{rock.pk}/milestones/", {"title": "Order die"}, **HX)
    assert "Order die" in resp.content.decode()
    c.post(f"/rocks/{rock.pk}/milestones/", {"title": "Install"}, **HX)
    a, b = rock.milestones.order_by("sort")
    c.post(f"/milestones/{a.pk}/", {"done": "1"}, **HX)
    a.refresh_from_db()
    assert a.done and a.done_at
    assert c.post(f"/rocks/{rock.pk}/milestones/reorder/", {"ids": [b.pk, a.pk]}).status_code == 204
    assert list(rock.milestones.order_by("sort").values_list("title", flat=True)) == ["Install", "Order die"]
    c.post(f"/milestones/{a.pk}/", {"delete": "1"}, **HX)
    assert list(Milestone.objects.values_list("title", flat=True)) == ["Install"]


def test_rocks_reorder(as_user, teams, member, rock, quarter):
    second = Rock.objects.create(team=teams["ky"], quarter=quarter, title="Second", owner=member, sort=1)
    c = as_user(member, teams["ky"])
    assert c.post("/rocks/reorder/", {"ids": [second.pk, rock.pk]}).status_code == 204
    second.refresh_from_db()
    rock.refresh_from_db()
    assert (second.sort, rock.sort) == (0, 1)


def test_rock_detail_autosave(as_user, teams, member, rock):
    c = as_user(member, teams["ky"])
    resp = c.post(f"/rocks/{rock.pk}/", {"title": "New pellet die (v2)", "owner": member.pk, "status": "on_track", "autosave": "1"}, **HX)
    assert resp.status_code == 204
    rock.refresh_from_db()
    assert rock.title == "New pellet die (v2)"
    page = c.get(f"/rocks/{rock.pk}/").content.decode()
    assert "Weekly updates" in page and "13-week status" in page
