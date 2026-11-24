"""Site views put the site's own issues, to-dos and rocks first and show Company below as its own labeled group.

Never another site's items. Company views stay a roll-up. Company items keep their team, rank and permissions."""

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

OTHERS = {"ky": ("lr", "mabel"), "lr": ("ky", "mabel"), "mabel": ("ky", "lr")}


def split(body, marker):
    """(site part, company part) of a page, divided at the Company group's container."""
    i = body.index(marker)
    return body[:i], body[i:]


def test_site_issues_page_own_first_in_rank_order_then_company_group(member, admin, all_teams, world):
    ky = all_teams["ky"]
    ranked2 = Issue.objects.create(team=ky, title="KY ranked two", owner=member)
    ranked1 = Issue.objects.create(team=ky, title="KY ranked one", owner=member)
    ranked2.set_priority(2)
    ranked1.set_priority(1)
    co = world["issues"]["company"]
    co.set_priority(1)
    body = get(member, "/issues/", ky).content.decode()
    site, company = split(body, 'id="company-issues"')
    assert site.index("KY ranked one") < site.index("KY ranked two") < site.index("Issue ky")
    assert "Issue company" not in site and "Issue company" in company
    assert 'from Company, not Kentucky' in body
    for other in ("Issue lr", "Issue mabel"):
        assert other not in body
    assert ">Company</span>" in company and ">Kentucky</span>" not in company


@pytest.mark.parametrize("key", ["ky", "lr", "mabel"])
def test_every_site_sees_only_itself_plus_company(admin, member, other, all_teams, world, key):
    user = {"ky": member, "lr": other, "mabel": admin}[key]
    body = get(user, "/issues/", all_teams[key]).content.decode()
    site, company = split(body, 'id="company-issues"')
    assert f"Issue {key}" in site and "Issue company" in company
    for o in OTHERS[key]:
        assert f"Issue {o}" not in body


def test_long_term_tab_has_its_own_company_group(member, all_teams, world):
    Issue.objects.create(team=all_teams["company"], title="Company long one", horizon=Issue.LONG, owner=world["issues"]["company"].owner)
    Issue.objects.create(team=all_teams["ky"], title="KY long one", horizon=Issue.LONG, owner=member)
    body = get(member, "/issues/?list=long", all_teams["ky"]).content.decode()
    site, company = split(body, 'id="company-issues"')
    assert "KY long one" in site and "Company long one" in company
    assert "Issue company" not in body  # the short-term Company issue is on the other tab


def test_rank_buttons_apply_only_to_the_sites_own_issues(admin, member, all_teams, world):
    co = world["issues"]["company"]
    co.set_priority(2)
    body = get(admin, "/issues/", all_teams["ky"]).content.decode()
    site, company = split(body, 'id="company-issues"')
    assert f"/issues/{world['issues']['ky'].pk}/priority/" in site
    assert f"/issues/{co.pk}/priority/" not in body
    assert re.search(r'<span class="prio prio-on">2</span>', company)  # Company's own rank, read-only
    client_for(admin, all_teams["ky"]).post(f"/issues/{world['issues']['ky'].pk}/priority/", {"rank": "2"})
    co.refresh_from_db()
    assert co.priority == 2 and co.team == all_teams["company"]


def test_company_rank_buttons_still_work_on_the_company_view(admin, all_teams, world):
    co = world["issues"]["company"]
    body = get(admin, "/issues/", all_teams["company"]).content.decode()
    assert f"/issues/{co.pk}/priority/" in body and 'id="company-issues"' not in body


def test_tab_counts_are_the_sites_own_and_company_is_counted_separately(member, all_teams, world):
    Issue.objects.create(team=all_teams["ky"], title="KY second", owner=member)
    Issue.objects.create(team=all_teams["company"], title="Company second", owner=member)
    body = get(member, "/issues/", all_teams["ky"]).content.decode()
    assert re.search(r"Short-term <span[^>]*>2</span>", body)
    assert re.search(r"from Company, not Kentucky</span></h2>\s*<span[^>]*>2</span>", body)


def test_company_view_is_unchanged_a_roll_up_with_chips_and_no_group(admin, all_teams, world):
    for path in ("/issues/", "/todos/", "/rocks/"):
        assert "from Company, not" not in get(admin, path, all_teams["company"]).content.decode()
    body = get(admin, "/issues/", all_teams["company"]).content.decode()
    assert f"/issues/{co.pk}/priority/" in body and 'id="company-issues"' not in body


def test_tab_counts_are_the_sites_own_and_company_is_counted_separately(member, all_teams, world):
    Issue.objects.create(team=all_teams["ky"], title="KY second", owner=member)
    Issue.objects.create(team=all_teams["company"], title="Company second", owner=member)
    body = get(member, "/issues/", all_teams["ky"]).content.decode()
    assert re.search(r"Short-term <span[^>]*>2</span>", body)
    assert re.search(r"from Company, not Kentucky</span></h2>\s*<span[^>]*>2</span>", body)


def test_company_view_is_unchanged_a_roll_up_with_chips_and_no_group(admin, all_teams, world):
    for path in ("/issues/", "/todos/", "/rocks/"):
        body = get(admin, path, all_teams["company"]).content.decode()
        assert "from Company, not" not in body
        assert all(f"{path.strip('/').title()[:-1]} {k}" in body or k for k in ("company", "ky", "lr", "mabel"))
    body = get(admin, "/issues/", all_teams["company"]).content.decode()
    assert all(f"Issue {k}" in body for k in ("company", "ky", "lr", "mabel")) and body.count("site-chip") >= 4


def test_company_issue_keeps_its_team_and_can_be_solved_by_its_owner_from_a_site_view(admin, all_teams, world):
    co = world["issues"]["company"]
    c = client_for(admin, all_teams["ky"])
    r = c.post(f"/issues/{co.pk}/solve/", {"action": "solve", "resolution": "done", "next": "/issues/"})
    assert r.status_code == 302
    co.refresh_from_db()
    assert co.status == Issue.SOLVED and co.team == all_teams["company"]


def test_normal_permissions_decide_company_rows_on_a_site_view(admin, member, all_teams, world):
    co = Issue.objects.create(team=all_teams["company"], title="Company, owned by Kim", owner=member)
    mine, theirs = co, world["issues"]["company"]
    body = get(member, "/issues/", all_teams["ky"]).content.decode()
    _, company = split(body, 'id="company-issues"')
    assert f"/issues/{mine.pk}/delete/" in company       # Kim owns it
    assert f"/issues/{theirs.pk}/delete/" not in company  # Kim is neither its owner nor on Company
    c = client_for(member, all_teams["ky"])
    assert c.post(f"/issues/{theirs.pk}/delete/").status_code == 403
    assert Issue.objects.filter(pk=theirs.pk).exists()
    assert c.post(f"/issues/{mine.pk}/delete/").status_code == 302
    assert not Issue.objects.filter(pk=mine.pk).exists()
    assert client_for(admin, all_teams["ky"]).post(f"/issues/{theirs.pk}/delete/").status_code == 302


def test_deleting_a_company_issue_recompacts_company_ranks_only(admin, member, all_teams, world):
    a = Issue.objects.create(team=all_teams["company"], title="CA", owner=admin)
    b = Issue.objects.create(team=all_teams["company"], title="CB", owner=admin)
    k = world["issues"]["ky"]
    a.set_priority(1), b.set_priority(2), k.set_priority(2)
    client_for(admin, all_teams["ky"]).post(f"/issues/{a.pk}/delete/")
    b.refresh_from_db(), k.refresh_from_db()
    assert (b.priority, k.priority) == (1, 2)


# ---- to-dos -------------------------------------------------------------------------------------------

def test_site_todos_own_first_then_company_group_never_other_sites(member, all_teams, world):
    body = get(member, "/todos/", all_teams["ky"]).content.decode()
    site, company = split(body, 'id="company-todos"')
    assert "Todo ky" in site and "Todo company" not in site and "Todo company" in company
    assert "Todo lr" not in body and "Todo mabel" not in body
    assert "Private KY" not in body
    assert "from Company, not Kentucky" in body


def test_company_todos_group_respects_the_open_filter_and_privacy(admin, member, all_teams, world):
    done = Todo.objects.create(team=all_teams["company"], title="Company finished", owner=admin, created_by=admin, done=True, done_at=timezone.now())
    Todo.objects.create(team=all_teams["company"], title="Company private", owner=admin, created_by=admin, is_private=True)
    assert "Company finished" not in get(member, "/todos/", all_teams["ky"]).content.decode()
    recent = get(member, "/todos/?show=recent", all_teams["ky"]).content.decode()
    assert "Company finished" in recent and "Company private" not in recent
    assert done.team == all_teams["company"]


def test_site_todo_completion_counts_only_the_site(member, all_teams, world):
    body = get(member, "/todos/", all_teams["ky"]).content.decode()
    assert "Kentucky team" in body and "All teams" not in body
    sect = body[body.index("Kentucky to-dos"):]
    assert re.search(r">\s*1\s*</span>", sect)  # the site's own single open to-do


# ---- rocks --------------------------------------------------------------------------------------------

def test_site_rocks_own_first_then_company_group_and_summary_counts_own_only(member, all_teams, world):
    body = get(member, "/rocks/", all_teams["ky"]).content.decode()
    site, company = split(body, 'id="company-rocks"')
    assert "Rock ky" in site and "Rock company" not in site and "Rock company" in company
    assert "Rock lr" not in body and "Rock mabel" not in body
    assert re.search(r'stat-label">Rocks</div><div class="stat-value">1<', body)


def test_a_site_cannot_reorder_company_rocks(member, all_teams, world, cur_q):
    co = world["rocks"]["company"]
    co.sort = 7
    co.save()
    client_for(member, all_teams["ky"]).post("/rocks/sort/", {"ids": f"{co.pk},{world['rocks']['ky'].pk}"})
    co.refresh_from_db()
    assert co.sort == 7


# ---- L10 ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("section,needle,marker", [("ids", "Issue", None), ("todos", "Todo", None), ("rocks", "Rock", None)])
def test_site_l10_sections_show_own_then_company_never_other_sites(member, admin, all_teams, world, cur_q, section, needle, marker):
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate(), facilitator=member)
    meeting.attendees.add(member, admin)  # Kim (Kentucky) and Ada (owns the Company items)
    body = client_for(member).get(f"/meetings/{meeting.pk}/?s={section}").content.decode()
    group = body.index("from Company, not Kentucky")
    assert body.index(f"{needle} ky") < group < body.index(f"{needle} company")
    assert f"{needle} lr" not in body and f"{needle} mabel" not in body


def test_l10_ids_company_rows_are_read_only_for_rank_and_follow_normal_permissions(member, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate(), facilitator=member)
    co = world["issues"]["company"]
    co.set_priority(1)
    body = client_for(member).get(f"/meetings/{meeting.pk}/?s=ids").content.decode()
    assert f"/issues/{co.pk}/priority/" not in body and f"/issues/{co.pk}/delete/" not in body
    assert f"/issues/{world['issues']['ky'].pk}/priority/" in body


def test_company_l10_is_unchanged_a_full_roll_up(admin, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["company"], quarter=cur_q, date=timezone.localdate(), facilitator=admin)
    for section, needle in (("ids", "Issue"), ("todos", "Todo"), ("rocks", "Rock")):
        body = client_for(admin).get(f"/meetings/{meeting.pk}/?s={section}").content.decode()
        assert all(f"{needle} {k}" in body for k in ("company", "ky", "lr", "mabel")), section
        assert "from Company, not" not in body
