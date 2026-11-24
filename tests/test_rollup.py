"""Company is a roll-up, not a business unit: the Company view shows everything across Company, Kentucky,
Le Roy and Mabel (each item chipped with its team), and a site's Scorecard opens with the Company measurables."""

import json
import re
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from api.models import ApiToken
from core.models import Quarter, Team
from issues.models import Issue
from meetings.models import Headline, Meeting
from rocks.models import Rock
from scorecard.models import Measurable, Plant, ScoreEntry
from scorecard.plants import layout
from scorecard.views import build_rows
from todos.models import Todo
from tests.conftest import client_for
from tests.test_api import bearer, rpc

pytestmark = pytest.mark.django_db


@pytest.fixture
def cur_q(db):
    q = Quarter.for_calendar(timezone.localdate())
    Quarter.objects.update(is_current=False)
    q.is_current = True
    q.save()
    return q


@pytest.fixture
def all_teams(teams):
    return {**teams, "mabel": Team.objects.create(name="Mabel", short_code="MB", sort=3)}


@pytest.fixture
def world(all_teams, admin, member, other, ky_peer, cur_q):
    """One of everything on every team, so a roll-up has something to show and a site view something to hide."""
    t = all_teams
    plants = {p.slug: p for p in Plant.objects.all()}
    out = {"rocks": {}, "issues": {}, "todos": {}, "heads": {}}
    for key, owner in (("company", admin), ("ky", member), ("lr", other), ("mabel", admin)):
        out["rocks"][key] = Rock.objects.create(quarter=cur_q, team=t[key], title=f"Rock {key}", owner=owner)
        out["issues"][key] = Issue.objects.create(team=t[key], title=f"Issue {key}", owner=owner)
        out["todos"][key] = Todo.objects.create(team=t[key], title=f"Todo {key}", owner=owner, created_by=owner)
        out["heads"][key] = Headline.objects.create(team=t[key], text=f"Headline {key}", author=owner)
    out["todos"]["secret"] = Todo.objects.create(team=t["ky"], title="Private KY", owner=ky_peer, is_private=True, created_by=ky_peer)
    out["pipe"] = Measurable.objects.create(
        team=t["company"], title="Total pipeline", unit=Measurable.UNIT_CURRENCY, goal=Decimal("11000000"), sort=0, owner=admin
    )
    out["leads"] = Measurable.objects.create(team=t["company"], title="New leads", sort=1, owner=admin)
    out["oee"] = {
        slug: Measurable.objects.create(team=t[key], plant=plants[slug], title="OEE", unit=Measurable.UNIT_PERCENT, goal=Decimal(85), sort=3, owner=owner)
        for slug, key, owner in (("kentucky", "ky", member), ("le-roy", "lr", other), ("mabel", "mabel", admin))
    }
    out["plants"] = plants
    return out


def get(user, path, team=None):
    return client_for(user, team).get(path)


def titles(body, prefix):
    return sorted(set(re.findall(rf"{prefix} (?:company|ky|lr|mabel)\b|{prefix} KY", body)))


# ---- rocks, to-dos, issues, headlines ----------------------------------------------------------------

def test_company_rocks_page_rolls_up_every_team_with_chips(admin, all_teams, world):
    body = get(admin, "/rocks/", all_teams["company"]).content.decode()
    for key in ("company", "ky", "lr", "mabel"):
        assert f"Rock {key}" in body
    assert body.count("site-chip") >= 4
    for name in ("Kentucky", "Le Roy", "Mabel"):
        assert f">{name}</span>" in body


def test_site_rocks_page_stays_one_team(member, all_teams, world):
    body = get(member, "/rocks/", all_teams["ky"]).content.decode()
    assert "Rock ky" in body and "Rock lr" not in body and "Rock mabel" not in body
    assert ">Kentucky</span>" in body and ">Le Roy</span>" not in body


def test_company_todos_roll_up_and_private_stay_private(admin, all_teams, world):
    body = get(admin, "/todos/", all_teams["company"]).content.decode()
    for key in ("company", "ky", "lr", "mabel"):
        assert f"Todo {key}" in body
    assert "Private KY" not in body
    assert body.count("site-chip") >= 4


def test_a_private_todo_still_shows_to_its_owner_in_the_company_view(ky_peer, all_teams, world):
    assert "Private KY" in get(ky_peer, "/todos/", all_teams["company"]).content.decode()


def test_site_todos_unchanged(member, all_teams, world):
    body = get(member, "/todos/", all_teams["ky"]).content.decode()
    assert "Todo ky" in body and "Todo lr" not in body and "Todo mabel" not in body
    assert body.index("Todo ky") < body.index("Todo company")  # Company is a labeled group below the site's own


def test_company_issues_roll_up_and_site_issues_do_not(admin, member, all_teams, world):
    body = get(admin, "/issues/", all_teams["company"]).content.decode()
    for key in ("company", "ky", "lr", "mabel"):
        assert f"Issue {key}" in body
    assert "site-chip" in body
    ky = get(member, "/issues/", all_teams["ky"]).content.decode()
    assert "Issue ky" in ky and "Issue lr" not in ky and "Issue mabel" not in ky
    assert ky.index("Issue ky") < ky.index("Issue company")  # Company shown below, see test_site_company_groups.py


def test_company_l10_runs_on_everything_a_site_l10_on_its_own(admin, member, all_teams, world, cur_q):
    lead = Meeting.objects.create(team=all_teams["company"], quarter=cur_q, date=timezone.localdate())
    lead.attendees.add(admin)
    ky = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate())
    ky.attendees.add(member)
    c = client_for(admin)
    for section, needle in (("rocks", "Rock"), ("todos", "Todo"), ("ids", "Issue")):
        body = c.get(f"/meetings/{lead.pk}/?s={section}").content.decode()
        assert all(f"{needle} {k}" in body for k in ("company", "ky", "lr", "mabel")), section
    heads = c.get(f"/meetings/{lead.pk}/?s=headlines").content.decode()
    assert all(f"Headline {k}" in heads for k in ("company", "ky", "lr", "mabel"))
    c = client_for(member)
    body = c.get(f"/meetings/{ky.pk}/?s=todos").content.decode()
    assert "Todo ky" in body and "Todo lr" not in body


def test_meetings_list_rolls_up(admin, member, all_teams, world, cur_q):
    Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate())
    Meeting.objects.create(team=all_teams["lr"], quarter=cur_q, date=timezone.localdate())
    body = get(admin, "/meetings/", all_teams["company"]).content.decode()
    assert "Kentucky L10" in body and "Le Roy L10" in body
    assert "Le Roy L10" not in get(member, "/meetings/", all_teams["ky"]).content.decode()


def test_company_dashboard_counts_cover_every_team(admin, all_teams, world):
    body = get(admin, "/", all_teams["company"]).content.decode()
    assert "Company pulse, all teams" in body
    assert re.search(r"Open issues</div><span class=\"stat-value\">4</span>", body)
    assert "4 rocks" in body
    ky = get(admin, "/", all_teams["ky"]).content.decode()
    assert re.search(r"Open issues</div><span class=\"stat-value\">1</span>", ky) and "1 rocks" in ky


def test_new_items_from_the_company_view_are_filed_under_company(admin, all_teams, world):
    c = client_for(admin, all_teams["company"])
    c.post("/issues/new/", {"title": "Filed from Company", "horizon": Issue.SHORT})
    assert Issue.objects.get(title="Filed from Company").team == all_teams["company"]


def test_people_list_in_company_view_shows_everyone(admin, member, other, all_teams, world):
    body = get(admin, "/people/", all_teams["company"]).content.decode()
    link = lambda u: f'href="/people/{u.pk}/"'
    assert link(member) in body and link(other) in body
    ky = get(admin, "/people/", all_teams["ky"]).content.decode()
    assert link(member) in ky and link(other) not in ky


# ---- the Scorecard -----------------------------------------------------------------------------------

def row_ids(body):
    return [int(x) for x in re.findall(r'id="m-(\d+)"', body)]


def test_company_scorecard_is_company_rows_then_plant_sub_rows(admin, all_teams, world):
    body = get(admin, "/scorecard/", all_teams["company"]).content.decode()
    oee = world["oee"]
    assert row_ids(body) == [world["pipe"].pk, world["leads"].pk, oee["kentucky"].pk, oee["le-roy"].pk, oee["mabel"].pk]
    assert 'sc-group-label">Company<' in body and 'sc-group-label">OEE<' in body
    assert "Company numbers, shown on every site" not in body


@pytest.mark.parametrize("key,slug", [("ky", "kentucky"), ("lr", "le-roy"), ("mabel", "mabel")])
def test_each_site_scorecard_opens_with_company_measurables_then_its_own(admin, all_teams, world, key, slug):
    body = get(admin, f"/scorecard/?team={all_teams[key].slug}").content.decode()
    assert row_ids(body) == [world["pipe"].pk, world["leads"].pk, world["oee"][slug].pk]
    label = all_teams[key].name
    assert body.index('sc-group-label">Company<') < body.index("Total pipeline") < body.index(f'sc-group-label">{label}<')
    assert "Company numbers, shown on every site" in body
    assert body.index(f'sc-group-label">{label}<') < body.index(f'id="m-{world["oee"][slug].pk}"')
    # The site's own row keeps its full title, not a plant sub-row label.
    own = re.search(rf'<tr id="m-{world["oee"][slug].pk}".*?</tr>', body, re.S).group(0)
    assert ">OEE</button>" in own


def test_site_scorecard_hides_other_sites_measurables(admin, all_teams, world):
    body = get(admin, f"/scorecard/?team={all_teams['ky'].slug}").content.decode()
    assert f'id="m-{world["oee"]["le-roy"].pk}"' not in body and f'id="m-{world["oee"]["mabel"].pk}"' not in body


def test_company_measurables_on_a_site_scorecard_follow_existing_permissions(member, all_teams, world):
    rows = {r.measurable.pk: r for r in build_rows(
        [world["pipe"], world["oee"]["kentucky"]], [], member, grouped=True, plant=world["plants"]["kentucky"]
    )}
    assert rows[world["pipe"].pk].editable is False and rows[world["oee"]["kentucky"].pk].editable is True


def test_company_values_show_on_the_site_scorecard_as_whole_dollars(admin, all_teams, world, cur_q):
    ScoreEntry.objects.create(measurable=world["pipe"], week_start=cur_q.weeks()[0], value=Decimal("-116000"))
    body = get(admin, f"/scorecard/?team={all_teams['lr'].slug}").content.decode()
    assert "-$116,000" in body


def test_site_layout_company_then_the_plant(world):
    ordered, groups = layout(Measurable.objects.filter(plant__isnull=True) | Measurable.objects.filter(plant=world["plants"]["mabel"]), world["plants"]["mabel"])
    assert [m.pk for m in ordered] == [world["pipe"].pk, world["leads"].pk, world["oee"]["mabel"].pk]
    assert groups[world["oee"]["mabel"].pk] == ("Mabel", True, False) and groups[world["pipe"].pk] == ("Company", True, False)


def test_new_measurable_on_a_site_scorecard_defaults_to_that_plant(member, all_teams, world):
    body = client_for(member, all_teams["ky"]).get("/scorecard/new/").content.decode()
    select = re.search(r'<select name="plant".*?</select>', body, re.S).group(0)
    assert "Company" in select


def test_l10_scorecard_for_a_site_has_the_company_section(member, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["lr"], quarter=cur_q, date=timezone.localdate())
    meeting.attendees.add(member)
    body = client_for(member).get(f"/meetings/{meeting.pk}/?s=scorecard").content.decode()
    assert row_ids(body) == [world["pipe"].pk, world["leads"].pk, world["oee"]["le-roy"].pk]
    assert 'sc-group-label">Company<' in body


# ---- REST API and MCP --------------------------------------------------------------------------------

def api(raw, path, **params):
    return Client().get(f"/api/v1/{path}", params, **bearer(raw))


def test_api_defaults_are_unchanged_without_include_all(admin, all_teams, world):
    _, raw = ApiToken.issue(admin, "t")
    issues = api(raw, "issues", team="company").json()["data"]
    assert [i["title"] for i in issues] == ["Issue company"]
    todos = api(raw, "todos", team="company", owner="all").json()["data"]
    assert {t["team"] for t in todos} == {"company"}


def test_include_all_rolls_company_queries_up(admin, all_teams, world):
    _, raw = ApiToken.issue(admin, "t")
    issues = api(raw, "issues", team="company", include_all="true").json()["data"]
    assert {i["team"] for i in issues} == {t.slug for t in all_teams.values()}
    rocks = api(raw, "rocks", team="company", include_all="true").json()["data"]
    assert len(rocks) == 4
    heads = api(raw, "headlines", team="company", include_all="true").json()["data"]
    assert {h["team"] for h in heads} == {t.slug for t in all_teams.values()}
    todos = api(raw, "todos", team="company", owner="all", include_all="true").json()["data"]
    assert {t["team"] for t in todos} == {t.slug for t in all_teams.values()}


def test_include_all_is_ignored_for_a_site_team(admin, all_teams, world):
    _, raw = ApiToken.issue(admin, "t")
    issues = api(raw, "issues", team="kentucky", include_all="true").json()["data"]
    assert {i["team"] for i in issues} == {"kentucky"}


def test_include_all_never_exposes_private_todos(admin, all_teams, world):
    _, raw = ApiToken.issue(admin, "t")
    todos = api(raw, "todos", team="company", owner="all", include_all="true").json()["data"]
    assert "Private KY" not in [t["title"] for t in todos]


def test_get_scorecard_include_all_adds_company_measurables_to_a_site(admin, all_teams, world):
    _, raw = ApiToken.issue(admin, "t")
    plain = api(raw, "scorecard", team="kentucky").json()["data"]["measurables"]
    assert [m["title"] for m in plain] == ["OEE"]
    both = api(raw, "scorecard", team="kentucky", include_all="true").json()["data"]["measurables"]
    assert [m["title"] for m in both] == ["Total pipeline", "New leads", "OEE"]


def test_mcp_exposes_include_all_and_still_accepts_old_calls(admin, all_teams, world):
    _, raw = ApiToken.issue(admin, "t")
    tools = {t["name"]: t for t in rpc(raw, "tools/list").json()["result"]["tools"]}
    assert "include_all" in tools["list_issues"]["inputSchema"]["properties"]
    r = rpc(raw, "tools/call", {"name": "list_issues", "arguments": {"team": "company", "include_all": True}}).json()
    payload = json.loads(r["result"]["content"][0]["text"])
    assert len(payload) == 4
    r = rpc(raw, "tools/call", {"name": "list_issues", "arguments": {"team": "company"}}).json()
    assert len(json.loads(r["result"]["content"][0]["text"])) == 1


# ---- bug: editing a measurable from the side panel inside an L10 --------------------------------------

def _tag(html, needle):
    return re.search(rf"<(?:a|form)\b[^>]*{re.escape(needle)}[^>]*>", html).group(0)


def test_panel_edit_link_opts_out_of_boost_and_the_drawer_target(admin, world):
    body = get(admin, f"/scorecard/{world['pipe'].pk}/panel/").content.decode()
    link = _tag(body, f"/scorecard/{world['pipe'].pk}/edit/")
    for attr in ('hx-select="unset"', 'hx-target="unset"', 'hx-swap="unset"', 'hx-boost="false"'):
        assert attr in link


def test_edit_form_posts_to_its_own_url_not_the_current_one(admin, world):
    m = world["pipe"]
    body = get(admin, f"/scorecard/{m.pk}/edit/").content.decode()
    form = _tag(body, "card card-pad")
    assert f'action="/scorecard/{m.pk}/edit/"' in form and 'hx-boost="false"' in form
    new = get(admin, "/scorecard/new/").content.decode()
    assert 'action="/scorecard/new/"' in _tag(new, "card card-pad")


def test_posting_to_measurable_edit_updates_the_title(admin, world):
    m = world["pipe"]
    r = client_for(admin).post(f"/scorecard/{m.pk}/edit/", {
        "title": "Total pipeline (renamed)", "unit": m.unit, "goal_compare": m.goal_compare, "goal": "11000000",
        "trailing": "", "sort": 0, "plant": "",
    })
    assert r.status_code == 302
    m.refresh_from_db()
    assert m.title == "Total pipeline (renamed)"


def test_posting_measurable_fields_to_the_meeting_url_is_refused(admin, all_teams, world, cur_q):
    m = world["pipe"]
    meeting = Meeting.objects.create(team=all_teams["company"], quarter=cur_q, date=timezone.localdate())
    meeting.attendees.add(admin)
    r = client_for(admin).post(f"/meetings/{meeting.pk}/", {"title": "Hijacked", "unit": m.unit})
    assert r.status_code == 405
    m.refresh_from_db()
    assert m.title == "Total pipeline"
    assert client_for(admin).get(f"/meetings/{meeting.pk}/").status_code == 200


@pytest.mark.parametrize("path_fmt,key", [
    ("/rocks/{}/", "rock"), ("/issues/{}/", "issue"), ("/todos/{}/", "todo"), ("/chart/seats/{}/", "seat"),
])
def test_other_edit_forms_have_an_explicit_action_and_no_boost(admin, all_teams, world, path_fmt, key):
    from vision.models import Seat
    obj = {
        "rock": world["rocks"]["ky"], "issue": world["issues"]["ky"], "todo": world["todos"]["ky"],
        "seat": Seat.objects.create(title="Plant Manager", team=all_teams["ky"]),
    }[key]
    path = path_fmt.format(obj.pk)
    body = get(admin, path).content.decode()
    forms = [f for f in re.findall(r"<form\b[^>]*>", body) if 'method="post"' in f and "csrf" not in f and "logout" not in f]
    main = [f for f in forms if "card-pad" in f]
    assert main and all(f'action="{path}"' in f and 'hx-boost="false"' in f for f in main)
