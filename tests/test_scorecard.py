from decimal import Decimal

import pytest

from scorecard.models import Measurable, ScoreEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def oee(teams, member):
    return Measurable.objects.create(
        team=teams["ky"], title="OEE", owner=member, unit=Measurable.UNIT_PERCENT, goal_compare="gte", goal=Decimal(65), trailing="avg"
    )


def cell_states(html, title):
    """data-state of each cell in the row containing `title`."""
    row = html.split(f">{title}<", 1)[1].split("</tr>", 1)[0]
    return [chunk.split('"', 1)[0] for chunk in row.split('data-state="')[1:]]


def test_scorecard_colors_cells_against_goal(as_user, teams, member, quarter, oee):
    w = quarter.weeks()
    ScoreEntry.objects.create(measurable=oee, week_start=w[0], value=Decimal("70"))
    ScoreEntry.objects.create(measurable=oee, week_start=w[1], value=Decimal("60"))
    ScoreEntry.objects.create(measurable=oee, week_start=w[2], value=Decimal("65"))
    html = as_user(member, teams["ky"]).get("/scorecard/").content.decode()
    states = cell_states(html, "OEE")
    assert states[:4] == ["green", "red", "green", ""]
    assert len(states) == 13
    assert "65%" in html  # trailing average of 70/60/65


def test_lte_goal_colors_inverse(as_user, teams, member, quarter):
    m = Measurable.objects.create(team=teams["ky"], title="Complaints", owner=member, goal_compare="lte", goal=Decimal(2))
    ScoreEntry.objects.create(measurable=m, week_start=quarter.weeks()[0], value=Decimal(1))
    ScoreEntry.objects.create(measurable=m, week_start=quarter.weeks()[1], value=Decimal(3))
    html = as_user(member, teams["ky"]).get("/scorecard/").content.decode()
    assert cell_states(html, "Complaints")[:2] == ["green", "red"]


def test_inline_cell_entry_returns_colored_cell(as_user, teams, member, quarter, oee):
    c = as_user(member, teams["ky"])
    week = quarter.weeks()[3].isoformat()
    cols = ",".join(w.isoformat() for w in quarter.weeks())
    r = c.post(f"/scorecard/{oee.pk}/cell/{week}/", {"value": "58.5%", "cols": cols, "trailing": "1"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200
    body = r.content.decode()
    assert 'data-state="red"' in body and 'value="58.5"' in body
    assert "Drop to Issues" in body  # title cell refreshed out-of-band
    assert ScoreEntry.objects.get(measurable=oee).value == Decimal("58.5")

    r = c.post(f"/scorecard/{oee.pk}/cell/{week}/", {"value": "80", "cols": cols})
    assert 'data-state="green"' in r.content.decode()
    c.post(f"/scorecard/{oee.pk}/cell/{week}/", {"value": "", "cols": cols})
    assert not ScoreEntry.objects.exists()


def test_bad_value_shows_error_and_keeps_data(as_user, teams, member, quarter, oee):
    week = quarter.weeks()[0]
    ScoreEntry.objects.create(measurable=oee, week_start=week, value=Decimal(70))
    r = as_user(member, teams["ky"]).post(f"/scorecard/{oee.pk}/cell/{week.isoformat()}/", {"value": "lots"})
    assert "Enter a number" in r.content.decode()
    assert ScoreEntry.objects.get().value == Decimal(70)


def test_yes_no_measurable(as_user, teams, member, quarter):
    m = Measurable.objects.create(team=teams["ky"], title="Huddle held", owner=member, unit=Measurable.UNIT_YESNO, goal_compare="eq", goal=Decimal(1))
    week = quarter.weeks()[0].isoformat()
    r = as_user(member, teams["ky"]).post(f"/scorecard/{m.pk}/cell/{week}/", {"value": "no"})
    assert 'data-state="red"' in r.content.decode()


def test_only_owner_or_admin_can_enter_numbers(as_user, teams, ky_peer, admin, quarter, oee):
    week = quarter.weeks()[0].isoformat()
    assert as_user(ky_peer).post(f"/scorecard/{oee.pk}/cell/{week}/", {"value": "1"}).status_code == 403
    assert as_user(admin).post(f"/scorecard/{oee.pk}/cell/{week}/", {"value": "1"}).status_code == 200
    html = as_user(ky_peer, teams["ky"]).get("/scorecard/").content.decode()
    assert f'/scorecard/{oee.pk}/cell/' not in html  # read-only for non-owners


def test_add_measurable(as_user, teams, member, quarter):
    r = as_user(member, teams["ky"]).post(
        "/scorecard/new/", {"title": "Downtime hrs", "owner": member.pk, "unit": "number", "goal_compare": "lte", "goal": "4", "trailing": "total", "sort": 0}
    )
    assert r.status_code == 302
    m = Measurable.objects.get(title="Downtime hrs")
    assert m.team == teams["ky"] and m.goal == Decimal(4)
