"""Issues are tagged by site: a chip everywhere, a Site select on create/edit, and a site filter on Company."""

import re

import pytest
from django.utils import timezone

from issues.models import Issue
from meetings.models import Meeting
from rocks.models import Rock
from todos.models import Todo
from tests.conftest import client_for
from tests.test_rollup import all_teams, cur_q, get, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


def chips(body):
    return re.findall(r'site-chip" title="Site">([^<]+)<', body)


def issue_row(body, issue):
    return re.search(rf'id="issue-{issue.pk}".*?(?=id="issue-\d+"|</body>)', body, re.S).group(0)


def test_every_issue_row_has_a_site_chip_on_a_site_view_too(member, all_teams, world):
    body = get(member, "/issues/", all_teams["ky"]).content.decode()
    assert "Kentucky" in re.search(r'id="issue-\d+".*?</div>\s*</div>\s*</div>', body, re.S).group(0)
    assert chips(body).count("Kentucky") >= 1


def test_company_view_chips_name_each_site_in_short_and_long_lists(admin, all_teams, world):
    Issue.objects.create(team=all_teams["lr"], title="Long one", horizon=Issue.LONG, owner=admin)
    short = get(admin, "/issues/", all_teams["company"]).content.decode()
    assert set(chips(short)) >= {"Company", "Kentucky", "Le Roy", "Mabel"}
    long = get(admin, "/issues/?list=long", all_teams["company"]).content.decode()
    assert "Long one" in long and "Le Roy" in issue_row(long, Issue.objects.get(title="Long one"))


def test_l10_ids_section_shows_the_chip_on_site_and_company_meetings(admin, member, all_teams, world, cur_q):
    for key, user in (("company", admin), ("ky", member)):
        m = Meeting.objects.create(team=all_teams[key], quarter=cur_q, date=timezone.localdate())
        m.attendees.add(user)
        body = client_for(user).get(f"/meetings/{m.pk}/?s=ids").content.decode()
        assert "Kentucky" in chips(body)
    assert "Mabel" in chips(client_for(admin).get(f"/meetings/{m.pk - 1}/?s=ids").content.decode())


def test_issue_detail_shows_the_site_chip(member, all_teams, world):
    body = get(member, f"/issues/{world['issues']['ky'].pk}/").content.decode()
    assert "Kentucky" in chips(body)


def test_todos_and_rocks_show_chips_on_site_views_too(member, all_teams, world):
    assert "Kentucky" in chips(get(member, "/todos/", all_teams["ky"]).content.decode())
    assert "Kentucky" in chips(get(member, "/rocks/", all_teams["ky"]).content.decode())


def test_create_form_has_a_site_select_defaulting_to_the_current_team(member, admin, all_teams, world):
    body = get(member, "/issues/", all_teams["ky"]).content.decode()
    sel = re.search(r'<select name="team".*?</select>', body, re.S).group(0)
    assert re.search(rf'<option value="{all_teams["ky"].pk}" selected>Kentucky', sel)
    co = re.search(r'<select name="team".*?</select>', get(admin, "/issues/", all_teams["company"]).content.decode(), re.S).group(0)
    assert re.search(rf'<option value="{all_teams["company"].pk}" selected>Company', co)


def test_create_files_under_the_chosen_site_and_defaults_to_the_current_team(admin, all_teams, world):
    c = client_for(admin, all_teams["company"])
    c.post("/issues/new/", {"title": "To Mabel", "team": all_teams["mabel"].pk, "horizon": Issue.SHORT})
    c.post("/issues/new/", {"title": "No site given", "horizon": Issue.SHORT})
    assert Issue.objects.get(title="To Mabel").team == all_teams["mabel"]
    assert Issue.objects.get(title="No site given").team == all_teams["company"]


def test_a_member_cannot_file_an_issue_on_a_site_they_are_not_on(member, all_teams, world):
    client_for(member, all_teams["ky"]).post("/issues/new/", {"title": "Sneaky", "team": all_teams["lr"].pk, "horizon": Issue.SHORT})
    assert not Issue.objects.filter(title="Sneaky").exists()


def test_edit_form_has_a_site_select_and_changing_it_moves_the_issue(admin, all_teams, world):
    issue = world["issues"]["ky"]
    page = get(admin, f"/issues/{issue.pk}/").content.decode()
    assert re.search(r'<select name="team"', page) and ">Site<" in page
    r = client_for(admin).post(f"/issues/{issue.pk}/", {
        "title": issue.title, "team": all_teams["lr"].pk, "owner": issue.owner_id or "", "horizon": issue.horizon, "description": "",
    })
    assert r.status_code == 302
    issue.refresh_from_db()
    assert issue.team == all_teams["lr"]
    assert issue.title in get(admin, "/issues/", all_teams["lr"]).content.decode()
    assert issue.title not in get(admin, "/issues/", all_teams["ky"]).content.decode()


def _edit(user, issue, team):
    return client_for(user).post(f"/issues/{issue.pk}/", {
        "title": issue.title, "team": team.pk, "owner": issue.owner_id or "", "horizon": issue.horizon, "description": "",
    })


def test_moving_keeps_the_rank_when_free_and_clears_it_when_taken(admin, all_teams, world):
    ky, lr = world["issues"]["ky"], world["issues"]["lr"]
    ky.set_priority(1)
    _edit(admin, ky, all_teams["mabel"])
    ky.refresh_from_db()
    assert ky.team == all_teams["mabel"] and ky.priority == 1

    lr.set_priority(2)
    ky.set_priority(2)
    _edit(admin, ky, all_teams["lr"])
    ky.refresh_from_db(), lr.refresh_from_db()
    assert ky.team == all_teams["lr"] and ky.priority is None and lr.priority == 2
    ranks = Issue.objects.filter(team=all_teams["lr"], horizon=Issue.SHORT, status=Issue.OPEN, priority__isnull=False)
    assert [i.priority for i in ranks] == [2]


def test_a_member_cannot_move_an_issue_to_a_site_they_are_not_on(member, all_teams, world):
    issue = world["issues"]["ky"]
    _edit(member, issue, all_teams["lr"])
    issue.refresh_from_db()
    assert issue.team == all_teams["ky"]


def test_saving_without_a_site_field_keeps_the_issue_where_it_is(admin, all_teams, world):
    issue = world["issues"]["ky"]
    client_for(admin).post(f"/issues/{issue.pk}/", {"title": "Renamed", "owner": "", "horizon": issue.horizon, "description": ""})
    issue.refresh_from_db()
    assert issue.title == "Renamed" and issue.team == all_teams["ky"]


def test_company_site_filter(admin, all_teams, world):
    c = client_for(admin, all_teams["company"])
    body = c.get("/issues/").content.decode()
    assert 'id="site-filter"' in body and all(f">{n}</a>" in body for n in ("All", "Company", "Kentucky", "Le Roy", "Mabel"))
    for key, slug in (("ky", "kentucky"), ("lr", "le-roy"), ("mabel", "mabel"), ("company", "company")):
        page = c.get(f"/issues/?site={slug}").content.decode()
        assert f"Issue {key}" in page
        assert all(f"Issue {k}" not in page for k in ("company", "ky", "lr", "mabel") if k != key)
    allp = c.get("/issues/?site=all").content.decode()
    assert all(f"Issue {k}" in allp for k in ("company", "ky", "lr", "mabel"))
    long = c.get("/issues/?list=long&site=kentucky").content.decode()
    assert "list=short&site=kentucky" in long


def test_site_filter_is_not_offered_on_a_site_view_and_cannot_widen_it(member, all_teams, world):
    body = client_for(member, all_teams["ky"]).get("/issues/?site=mabel").content.decode()
    assert 'id="site-filter"' not in body and "Issue mabel" not in body and "Issue ky" in body
