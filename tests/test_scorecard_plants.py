"""One company Scorecard. Every measurable has a plant (Company, Kentucky, Le Roy or Mabel), laid out like
Battle Planner: Company rows first, then plant rows grouped by measurable name with a sub-row per plant."""

import datetime as dt
import json
import re
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.utils import timezone

from api.models import ApiToken
from core.importer import BattlePlannerImporter
from core.models import Quarter, Team, monday_of
from meetings.models import Meeting
from scorecard.models import Measurable, Plant, ScoreEntry
from scorecard.plants import assign_plant, layout
from scorecard.units import title_is_money, unit_for
from scorecard.values_csv import load_values_csv
from scorecard.views import build_rows
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
def quarter(cur_q):
    return cur_q


@pytest.fixture
def plants():
    return {p.slug: p for p in Plant.objects.all()}


@pytest.fixture
def board(teams, plants, admin, member, other, cur_q):
    """Two Company rows, and OEE on all three plants (created out of order on purpose)."""
    co = teams["company"]
    pipe = Measurable.objects.create(
        team=co, title="Total pipeline", unit=Measurable.UNIT_CURRENCY, goal=Decimal("11000000"), sort=0, owner=admin
    )
    leads = Measurable.objects.create(team=co, title="New leads", unit=Measurable.UNIT_NUMBER, sort=1)
    oee = {}
    for slug, owner, goal, sort in [("mabel", other, 80, 5), ("kentucky", member, 85, 3), ("le-roy", other, 82, 4)]:
        oee[slug] = Measurable.objects.create(
            team=co, plant=plants[slug], title="OEE", unit=Measurable.UNIT_PERCENT, goal=Decimal(goal), sort=sort, owner=owner
        )
    return {"pipe": pipe, "leads": leads, **{f"oee_{k}": v for k, v in oee.items()}}


def _page(user, path="/scorecard/", **kw):
    c = Client()
    c.force_login(user)
    return c.get(path, **kw)


# ---- the three plants exist; new measurables are Company ---------------------------------------

def test_the_three_plants_exist_from_the_start():
    assert [p.name for p in Plant.objects.all()] == ["Kentucky", "Le Roy", "Mabel"]


def test_new_measurable_defaults_to_company(as_user, teams, member, quarter):
    c = as_user(member, teams["ky"])
    r = c.post("/scorecard/new/", {"title": "Web leads", "unit": "number", "goal_compare": "gte", "trailing": "", "sort": 0})
    assert r.status_code == 302
    m = Measurable.objects.get(title="Web leads")
    assert m.plant is None and m.plant_name == "Company" and m.team == teams["company"]


def test_new_measurable_form_offers_company_first_and_the_plants(as_user, member, teams, quarter):
    body = as_user(member, teams["ky"]).get("/scorecard/new/").content.decode()
    select = re.search(r'<select name="plant".*?</select>', body, re.S).group(0)
    assert select.index("Company") < select.index("Kentucky") < select.index("Le Roy") < select.index("Mabel")


def test_new_measurable_on_a_plant_joins_that_plants_team(as_user, teams, plants, member, quarter):
    c = as_user(member, teams["ky"])
    c.post("/scorecard/new/", {"title": "Scrap", "plant": plants["kentucky"].pk, "unit": "number", "goal_compare": "lte", "trailing": "", "sort": 0})
    m = Measurable.objects.get(title="Scrap")
    assert m.plant == plants["kentucky"] and m.team == teams["ky"]


# ---- the single scorecard ----------------------------------------------------------------------

def test_scorecard_has_the_team_switcher_and_quarter_picker(admin, teams, board, quarter):
    body = _page(admin).content.decode()
    assert 'href="?team=company"' in body and 'href="?team=kentucky"' in body
    assert 'name="quarter"' in body
    assert "Company · Q4 2026" in body


def test_company_and_unknown_team_params_show_the_whole_scorecard(admin, teams, board, quarter):
    plain = _page(admin, "/scorecard/?team=company").content.decode()
    rows = re.findall(r'id="m-(\d+)"', plain)
    assert len(rows) == 5 and rows == re.findall(r'id="m-(\d+)"', _page(admin).content.decode())


def test_company_rows_first_then_plants_grouped_by_name(admin, board, quarter):
    body = _page(admin).content.decode()
    ids = [int(x) for x in re.findall(r'id="m-(\d+)"', body)]
    assert ids == [board["pipe"].pk, board["leads"].pk, board["oee_kentucky"].pk, board["oee_le-roy"].pk, board["oee_mabel"].pk]
    assert body.count('class="sc-group"') == 2 and 'sc-group-label">OEE<' in body and 'sc-group-label">Company<' in body
    assert body.index("Total pipeline") < body.index('sc-group-label">OEE<') < body.index(">Kentucky</button>")
    assert body.index(">Kentucky</button>") < body.index(">Le Roy</button>") < body.index(">Mabel</button>")


def test_each_plant_row_keeps_its_own_owner_goal_and_colors(admin, board, cur_q):
    week = cur_q.weeks()[0]
    ScoreEntry.objects.create(measurable=board["oee_kentucky"], week_start=week, value=Decimal("90"))
    ScoreEntry.objects.create(measurable=board["oee_mabel"], week_start=week, value=Decimal("70"))
    body = _page(admin).content.decode()
    row = lambda m: re.search(rf'<tr id="m-{m.pk}".*?</tr>', body, re.S).group(0)
    ky, lr, mb = (row(board[k]) for k in ("oee_kentucky", "oee_le-roy", "oee_mabel"))
    assert "Kim Member" in ky and "≥ 85%" in ky and 'sc-green' in ky
    assert "Lee Other" in lr and "≥ 82%" in lr and "sc-green" not in lr and "sc-red" not in lr
    assert "≥ 80%" in mb and "sc-red" in mb


def test_only_company_rows_are_draggable(admin, board, quarter):
    body = _page(admin).content.decode()
    company_body, plant_body = re.search(r"<tbody(.*?)</tbody>\s*<tbody class=\"sc-plants\">(.*?)</tbody>", body, re.S).groups()
    assert "data-sortable" in company_body and f'id="m-{board["pipe"].pk}"' in company_body
    assert "data-sortable" not in plant_body and "drag-handle" not in plant_body


def test_reordering_company_rows_sticks(as_user, admin, teams, board, quarter):
    r = as_user(admin, teams["company"]).post("/scorecard/sort/", {"ids": f"{board['leads'].pk},{board['pipe'].pk}"})
    assert r.status_code == 204
    ids = [int(x) for x in re.findall(r'id="m-(\d+)"', _page(admin).content.decode())]
    assert ids[:2] == [board["leads"].pk, board["pipe"].pk]


def test_layout_orders_plants_by_plant_order_not_creation(board, plants):
    ordered, groups = layout(Measurable.objects.filter(active=True))
    assert [m.plant_name for m in ordered if m.title == "OEE"] == ["Kentucky", "Le Roy", "Mabel"]
    assert groups[board["oee_kentucky"].pk] == ("OEE", True, True) and groups[board["oee_mabel"].pk] == ("OEE", False, True)
    assert groups[board["pipe"].pk] == ("Company", True, False)


def test_single_plant_measurable_still_sits_under_its_name(admin, teams, plants, quarter):
    Measurable.objects.create(team=teams["ky"], plant=plants["kentucky"], title="Scrap rate", unit="percent")
    body = _page(admin).content.decode()
    assert 'sc-group-label">Scrap rate<' in body and ">Kentucky</button>" in body


# ---- green and red -----------------------------------------------------------------------------

def test_current_week_cell_is_still_green_or_red_and_no_goal_stays_neutral(admin, teams, cur_q):
    this_monday = monday_of(timezone.localdate())
    on = Measurable.objects.create(team=teams["company"], title="On", goal=Decimal(5), sort=0)
    off = Measurable.objects.create(team=teams["company"], title="Off", goal=Decimal(5), sort=1)
    free = Measurable.objects.create(team=teams["company"], title="Free", sort=2)
    for m, v in ((on, 9), (off, 1), (free, 3)):
        ScoreEntry.objects.create(measurable=m, week_start=this_monday, value=Decimal(v))
    rows = {r.measurable.title: r for r in build_rows([on, off, free], cur_q.weeks(), admin)}
    now = lambda t: next(c for c in rows[t].cells if c.is_now)
    assert (now("On").state, now("Off").state, now("Free").state) == ("green", "red", "")
    body = _page(admin).content.decode()
    cells = {t: re.search(rf'<tr id="m-{m.pk}".*?</tr>', body, re.S).group(0) for t, m in (("On", on), ("Off", off), ("Free", free))}
    assert re.search(r'sc-green[^"]*sc-now|sc-now[^"]*sc-green', cells["On"])
    assert re.search(r'sc-red[^"]*sc-now|sc-now[^"]*sc-red', cells["Off"])
    assert "sc-green" not in cells["Free"] and "sc-red" not in cells["Free"]
    assert "No goal" in cells["Free"]


def test_the_current_week_marker_never_paints_a_background():
    css = (Path(__file__).resolve().parent.parent / "static/css/sn.css").read_text()
    rules = re.findall(r"(\.sc-now[^{]*)\{([^}]*)\}", css)
    assert rules
    for selector, body in rules:
        assert "background" not in body.replace("background: var(--bolt)", "") or "::before" in selector
    assert not re.search(r"\.sc-now\s*\{[^}]*(background|box-shadow)", css)


def test_negative_dollars_show_as_minus_dollar_sign(admin, teams, plants, cur_q):
    m = Measurable.objects.create(
        team=teams["ky"], plant=plants["kentucky"], title="Difference of Actual vs Expected Revenue",
        unit=Measurable.UNIT_CURRENCY, goal=Decimal(0),
    )
    ScoreEntry.objects.create(measurable=m, week_start=cur_q.weeks()[0], value=Decimal("-116000"))
    body = _page(admin).content.decode()
    assert "-$116,000" in body and "-116000" not in body and "-116,000" not in body.replace("-$116,000", "")


# ---- one layout ---------------------------------------------------------------------------------

def test_every_row_uses_the_same_goal_and_title_columns(admin, board, quarter):
    body = _page(admin).content.decode()
    rows = re.findall(r"<tr id=\"m-\d+\".*?</tr>", body, re.S)
    assert len(rows) == 5
    for r in rows:
        assert r.count('class="sc-goal') == 1 and 'class="sc-sticky sc-title' in r
    css = (Path(__file__).resolve().parent.parent / "static/css/sn.css").read_text()
    assert re.search(r"\.sc-goal \{[^}]*min-width: 7\.5rem", css) and re.search(r"\.sc-title \{[^}]*max-width", css)


def test_drop_to_issues_button_is_compact_so_it_cannot_squeeze_the_row(admin, board, cur_q):
    ScoreEntry.objects.create(measurable=board["pipe"], week_start=cur_q.weeks()[0], value=Decimal(1))
    body = _page(admin).content.decode()
    row = re.search(rf'<tr id="m-{board["pipe"].pk}".*?</tr>', body, re.S).group(0)
    assert 'class="sc-actions"' in row and "sr-only\">Drop to Issues" in row


# ---- plant field in the side panel --------------------------------------------------------------

def test_panel_shows_a_plant_field_for_editors(admin, as_user, board, teams, quarter):
    body = as_user(admin, teams["company"]).get(f"/scorecard/{board['pipe'].pk}/panel/").content.decode()
    assert f'hx-post="/scorecard/{board["pipe"].pk}/plant/"' in body
    assert re.search(r'<option value="" selected>Company</option>', body)
    assert ">Kentucky</option>" in body and ">Le Roy</option>" in body and ">Mabel</option>" in body


def test_panel_plant_is_read_only_for_people_who_cannot_edit(as_user, board, ky_peer, teams, quarter):
    body = as_user(ky_peer, teams["ky"]).get(f"/scorecard/{board['oee_mabel'].pk}/panel/").content.decode()
    assert "/plant/" not in body and "Mabel" in body


def test_owner_can_change_the_plant_and_the_team_follows(as_user, board, member, teams, plants, quarter):
    m = Measurable.objects.create(team=teams["company"], title="Downtime", owner=member)
    c = as_user(member, teams["ky"])
    r = c.post(f"/scorecard/{m.pk}/plant/", {"plant": plants["kentucky"].pk}, HTTP_HX_REQUEST="true")
    assert r.status_code == 204 and r["HX-Refresh"] == "true"
    m.refresh_from_db()
    assert m.plant == plants["kentucky"] and m.team == teams["ky"]
    r = c.post(f"/scorecard/{m.pk}/plant/", {"plant": plants["kentucky"].pk})
    assert "HX-Refresh" not in r  # nothing changed
    r = c.post(f"/scorecard/{m.pk}/plant/", {"plant": ""})
    m.refresh_from_db()
    assert r.status_code == 204 and m.plant is None and m.team == teams["company"]


def test_changing_plant_is_permission_checked_and_validated(as_user, board, ky_peer, other, admin, teams, plants, quarter):
    pipe = board["pipe"]  # owned by the admin
    assert as_user(ky_peer, teams["ky"]).post(f"/scorecard/{pipe.pk}/plant/", {"plant": plants["mabel"].pk}).status_code == 403
    assert as_user(other, teams["lr"]).post(f"/scorecard/{pipe.pk}/plant/", {"plant": plants["mabel"].pk}).status_code == 403
    pipe.refresh_from_db()
    assert pipe.plant is None
    c = as_user(admin, teams["company"])
    assert c.post(f"/scorecard/{pipe.pk}/plant/", {"plant": "999"}).status_code == 400
    assert c.post(f"/scorecard/{pipe.pk}/plant/", {"plant": "mabel"}).status_code == 204
    pipe.refresh_from_db()
    assert pipe.plant == plants["mabel"]
    assert Client().post(f"/scorecard/{pipe.pk}/plant/", {"plant": ""}).status_code in (302, 403)


def test_unowned_company_row_is_editable_by_its_team_only(as_user, teams, plants, member, admin, quarter):
    m = Measurable.objects.create(team=teams["ky"], plant=plants["kentucky"], title="Scrap")
    assert as_user(member, teams["ky"]).post(f"/scorecard/{m.pk}/plant/", {"plant": ""}).status_code == 204
    m.refresh_from_db()
    assert m.plant is None and m.team == teams["company"]  # a plant team's row falls back to leadership
    assert as_user(member, teams["ky"]).post(f"/scorecard/{m.pk}/plant/", {"plant": ""}).status_code == 403


def test_assign_plant_keeps_a_non_plant_team_when_going_back_to_company(teams, plants, quarter):
    sales = Team.objects.create(name="Sales", sort=3)
    m = Measurable.objects.create(team=sales, title="Quotes")
    assert assign_plant(m, None) is False and m.team == sales
    assign_plant(m, plants["mabel"])  # no Mabel team: keeps the team it had
    assert m.plant == plants["mabel"] and m.team == sales
    assign_plant(m, None)
    assert m.plant is None and m.team == sales


# ---- migration -----------------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_migration_maps_plant_teams_to_plants_and_everything_else_to_company():
    executor = MigrationExecutor(connection)
    executor.migrate([("scorecard", "0003_backfill_currency_and_source")])
    old = MigrationExecutor(connection).loader.project_state([("scorecard", "0003_backfill_currency_and_source")]).apps
    Team_, M_ = old.get_model("core", "Team"), old.get_model("scorecard", "Measurable")
    co = Team_.objects.create(name="Company", slug="company", is_leadership=True, sort=0)
    ky = Team_.objects.create(name="Kentucky", slug="kentucky", short_code="KY", sort=1)
    lr = Team_.objects.create(name="Le Roy", slug="le-roy", short_code="LR", sort=2)
    mb = Team_.objects.create(name="MABEL", slug="mabel", sort=3)
    ops = Team_.objects.create(name="Operations", slug="operations", sort=4)
    made = {
        name: M_.objects.create(team=team, title=name, sort=i)
        for i, (name, team) in enumerate([("Rev", co), ("Ops", ops), ("OEE KY", ky), ("OEE LR", lr), ("OEE MB", mb), ("Quotes", ops)])
    }
    # Sort used to restart per team, so two teams can both have a row at sort 0.
    M_.objects.filter(pk=made["OEE KY"].pk).update(sort=0)
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
    new = MigrationExecutor(connection).loader.project_state(executor.loader.graph.leaf_nodes()).apps
    Measurable_ = new.get_model("scorecard", "Measurable")
    plant_of = {m.title: (m.plant.name if m.plant_id else None) for m in Measurable_.objects.select_related("plant")}
    assert plant_of == {"Rev": None, "Ops": None, "OEE KY": "Kentucky", "OEE LR": "Le Roy", "OEE MB": "Mabel", "Quotes": None}
    assert {m.team.name for m in Measurable_.objects.select_related("team")} == {"Company", "Kentucky", "Le Roy", "MABEL", "Operations"}
    assert sorted(Measurable_.objects.values_list("sort", flat=True)) == list(range(6))
    assert Team.objects.count() == 5  # the teams themselves are left alone


def test_migration_is_idempotent_and_the_dollar_backfill_flags_imported_money_rows(teams, quarter):
    migration = import_module("scorecard.migrations.0006_dollar_titles")
    imported = Measurable.objects.create(
        team=teams["ky"], title="Difference of Actual vs Expected Revenue", unit="number", legacy_id=77, legacy={"unit": "", "goal": ""}
    )
    manual = Measurable.objects.create(team=teams["ky"], title="Revenue calls", unit="number")
    ratio = Measurable.objects.create(team=teams["ky"], title="Labor to revenue ratio", unit="number", legacy_id=78, legacy={})
    migration.flag_dollars(django_apps, None)
    for m in (imported, manual, ratio):
        m.refresh_from_db()
    assert (imported.unit, manual.unit, ratio.unit) == ("currency", "number", "number")
    assign = import_module("scorecard.migrations.0005_assign_plants").assign
    assign(django_apps, None)
    once = list(Measurable.objects.order_by("pk").values_list("plant__name", "sort"))
    assign(django_apps, None)
    assert Plant.objects.count() == 3 and once == list(Measurable.objects.order_by("pk").values_list("plant__name", "sort"))
    assert {p for p, _ in once} == {"Kentucky"}  # all three sit on the Kentucky team


# ---- importer ------------------------------------------------------------------------------------

BP = [
    {"model": "core.facility", "pk": 1, "fields": {"name": "Company", "short_code": "CO", "sort": 0}},
    {"model": "core.facility", "pk": 2, "fields": {"name": "Kentucky", "short_code": "KY", "sort": 1}},
    {"model": "core.facility", "pk": 3, "fields": {"name": "Le Roy", "short_code": "LR", "sort": 2}},
    {"model": "core.facility", "pk": 4, "fields": {"name": "Mabel", "short_code": "MB", "sort": 3}},
    {"model": "core.scorecardmetric", "pk": 1, "fields": {"name": "Pipeline", "facility": 1, "unit": "$", "sort": 1, "active": True, "goal": "$11M", "direction": "up"}},
    {"model": "core.scorecardmetric", "pk": 2, "fields": {"name": "Web leads", "facility": None, "unit": "count", "sort": 2, "active": True, "goal": "", "direction": ""}},
    {"model": "core.scorecardmetric", "pk": 3, "fields": {"name": "OEE", "facility": 3, "unit": "%", "sort": 1, "active": True, "goal": "80", "direction": "up"}},
    {"model": "core.scorecardmetric", "pk": 4, "fields": {"name": "OEE", "facility": 2, "unit": "%", "sort": 1, "active": True, "goal": "85", "direction": "up"}},
    {"model": "core.scorecardmetric", "pk": 5, "fields": {"name": "Difference of Actual vs Expected Revenue", "facility": 2, "unit": "", "sort": 2, "active": True, "goal": "0", "direction": "up"}},
    {"model": "core.scorecardmetric", "pk": 6, "fields": {"name": "Rework", "facility": 4, "unit": "number", "sort": 3, "active": True, "goal": "$500", "direction": "down"}},
    {"model": "core.scorecardmetric", "pk": 7, "fields": {"name": "Labor to revenue ratio", "facility": 4, "unit": "", "sort": 4, "active": True, "goal": "", "direction": ""}},
]


def _run(refresh=False):
    return BattlePlannerImporter(json.loads(json.dumps(BP)), refresh=refresh).run()


def test_importer_maps_facility_to_plant_and_leaves_company_without_one():
    _run()
    plant = {m.legacy_id: m.plant_name for m in Measurable.objects.all()}
    assert plant == {1: "Company", 2: "Company", 3: "Le Roy", 4: "Kentucky", 5: "Kentucky", 6: "Mabel", 7: "Mabel"}
    assert Plant.objects.count() == 3  # existing plants are reused, never duplicated
    assert Team.objects.filter(name__in=["Kentucky", "Le Roy", "Mabel"]).count() == 3  # the teams still exist


def test_importer_flags_facility_dollar_metrics_as_currency():
    _run()
    by = {m.legacy_id: m.unit for m in Measurable.objects.all()}
    assert by[5] == "currency"  # revenue difference, no unit text
    assert by[6] == "currency"  # a $ goal on a plain number
    assert by[7] == "number"  # a ratio is not money
    assert by[1] == "currency" and by[2] == "number"


def test_importer_refresh_moves_a_measurable_back_to_its_facility_plant(plants):
    _run()
    m = Measurable.objects.get(legacy_id=3)
    assign_plant(m, None)
    assert Measurable.objects.get(legacy_id=3).plant is None
    _run(refresh=True)
    assert Measurable.objects.get(legacy_id=3).plant == plants["le-roy"]


def test_importer_creates_a_plant_for_a_new_facility():
    rows = BP + [
        {"model": "core.facility", "pk": 9, "fields": {"name": "Ohio", "short_code": "OH", "sort": 4}},
        {"model": "core.scorecardmetric", "pk": 20, "fields": {"name": "OEE", "facility": 9, "unit": "%", "sort": 9, "active": True}},
    ]
    BattlePlannerImporter(json.loads(json.dumps(rows))).run()
    assert Measurable.objects.get(legacy_id=20).plant.name == "Ohio"


def test_unit_heuristics():
    assert title_is_money("Difference of Actual vs Expected Revenue") and title_is_money("Total pipeline")
    assert not title_is_money("OEE") and not title_is_money("Revenue %") and not title_is_money("Open pipeline deals")
    assert unit_for("", "Revenue difference") == "currency" and unit_for("%", "Revenue difference") == "percent"
    assert unit_for("count", "Cash on hand") == "currency" and unit_for("", "Leads", "$5") == "currency"


# ---- csv -------------------------------------------------------------------------------------------

def test_values_csv_facility_is_the_plant(board, plants, quarter):
    res = load_values_csv(
        "metric,facility,week_start,value\nOEE,Kentucky,2026-11-02,88\nOEE,Mabel,2026-11-02,71\nTotal pipeline,Company,2026-11-02,9000000\n"
        "Total pipeline,,2026-11-09,9100000\nOEE,,2026-11-02,5\nOEE,Elsewhere,2026-11-02,5\n"
    )
    assert res.counts["created"] == 4 and res.counts["skipped"] == 2
    week = monday_of(dt.date(2026, 11, 2))
    assert ScoreEntry.objects.get(measurable=board["oee_kentucky"], week_start=week).value == 88
    assert ScoreEntry.objects.get(measurable=board["oee_mabel"], week_start=week).value == 71
    assert not ScoreEntry.objects.filter(measurable=board["oee_le-roy"]).exists()
    assert any("several measurables" in n for n in res.notes) and any("unknown facility" in n for n in res.notes)


# ---- L10 -------------------------------------------------------------------------------------------

def test_leadership_l10_shows_the_whole_scorecard_and_a_plant_l10_only_its_plant(board, teams, member, admin, cur_q):
    lead_meeting = Meeting.objects.create(team=teams["company"], quarter=cur_q, date=timezone.localdate())
    lead_meeting.attendees.add(admin)
    c = Client()
    c.force_login(admin)
    seg = c.get(f"/meetings/{lead_meeting.pk}/?s=scorecard&all=1").content.decode()
    assert len(re.findall(r'id="m-\d+"', seg)) == 5 and "Total pipeline" in seg and "Full scorecard" in seg
    assert 'href="/scorecard/"' in seg

    ky_meeting = Meeting.objects.create(team=teams["ky"], quarter=cur_q, date=timezone.localdate())
    ky_meeting.attendees.add(member)
    c = Client()
    c.force_login(member)
    seg = c.get(f"/meetings/{ky_meeting.pk}/?s=scorecard&all=1").content.decode()
    assert re.findall(r'id="m-(\d+)"', seg) == [str(board[k].pk) for k in ("pipe", "leads", "oee_kentucky")]
    assert "Company, then Kentucky" in seg and ">Le Roy</button>" not in seg


def test_non_plant_team_l10_shows_everything(board, teams, cur_q, admin):
    sales = Team.objects.create(name="Sales", sort=5)
    meeting = Meeting.objects.create(team=sales, quarter=cur_q, date=timezone.localdate())
    meeting.attendees.add(admin)
    c = Client()
    c.force_login(admin)
    assert len(re.findall(r'id="m-\d+"', c.get(f"/meetings/{meeting.pk}/?s=scorecard&all=1").content.decode())) == 5


# ---- dashboards ------------------------------------------------------------------------------------

def test_dashboard_and_person_dashboard_name_the_plant(board, member, other, as_user, teams, cur_q):
    own = as_user(member, teams["ky"]).get("/").content.decode()
    assert "Kim Member · Kentucky" in own
    theirs = as_user(member, teams["ky"]).get(f"/people/{other.pk}/dashboard/").content.decode()
    assert "Lee Other · Le Roy" in theirs and "Lee Other · Mabel" in theirs
    assert 'name="value"' not in theirs  # someone else's numbers stay read-only


def test_company_measurable_reads_company_on_the_dashboard(board, admin, as_user, teams, cur_q):
    assert "Ada Admin · Company" in as_user(admin, teams["company"]).get("/").content.decode()


# ---- API and MCP -----------------------------------------------------------------------------------

def test_api_scorecard_lists_everything_with_plants_and_filters(board, member, cur_q):
    _, raw = ApiToken.issue(member, "t")
    data = Client().get("/api/v1/scorecard", **bearer(raw)).json()["data"]
    assert [(m["title"], m["plant"]) for m in data["measurables"]] == [
        ("Total pipeline", "Company"), ("New leads", "Company"), ("OEE", "Kentucky"), ("OEE", "Le Roy"), ("OEE", "Mabel"),
    ]
    only = Client().get("/api/v1/scorecard", {"plant": "le-roy"}, **bearer(raw)).json()["data"]["measurables"]
    assert [m["plant"] for m in only] == ["Le Roy"]
    company = Client().get("/api/v1/scorecard", {"plant": "company"}, **bearer(raw)).json()["data"]["measurables"]
    assert [m["title"] for m in company] == ["Total pipeline", "New leads"]
    assert Client().get("/api/v1/scorecard", {"plant": "mars"}, **bearer(raw)).status_code == 400


def test_api_set_value_by_name_and_plant(board, other, member, cur_q):
    _, raw = ApiToken.issue(other, "t")
    week = cur_q.weeks()[0].isoformat()
    body = lambda **kw: json.dumps({"measurable": "OEE", "value": 77, "week": week, **kw})
    post = lambda **kw: Client().post("/api/v1/measurables/values", body(**kw), content_type="application/json", **bearer(raw))
    ambiguous = post()
    assert ambiguous.status_code == 400 and "plant" in ambiguous.json()["error"]
    ok = post(plant="le-roy")
    assert ok.status_code == 200 and ok.json()["data"]["plant"] == "Le Roy"
    assert ScoreEntry.objects.get(measurable=board["oee_le-roy"]).value == 77
    assert post(plant="kentucky").status_code == 403  # Lee does not own Kentucky's OEE


def test_mcp_tools_advertise_plant(board, member):
    _, raw = ApiToken.issue(member, "t")
    tools = {t["name"]: t for t in rpc(raw, "tools/list").json()["result"]["tools"]}
    assert "plant" in tools["get_scorecard"]["inputSchema"]["properties"]
    assert "plant" in tools["set_measurable_value"]["inputSchema"]["properties"]
    got = rpc(raw, "tools/call", {"name": "get_scorecard", "arguments": {"plant": "mabel"}}).json()["result"]["structuredContent"]
    assert [m["plant"] for m in got["measurables"]] == ["Mabel"]


def test_my_90_includes_the_plant(board, member, cur_q):
    _, raw = ApiToken.issue(member, "t")
    got = rpc(raw, "tools/call", {"name": "my_90", "arguments": {}}).json()["result"]["structuredContent"]
    assert [(m["title"], m["plant"]) for m in got["measurables"]] == [("OEE", "Kentucky")]
