"""Dollar measurables show as whole dollars everywhere, and the weekly values an assistant posts have a way in."""

import datetime as dt
import json
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.utils import timezone

from api.models import ApiToken
from core.importer import BattlePlannerImporter, parse_goal
from core.models import Quarter, Team, monday_of
from core.money import format_dollars
from meetings.models import Meeting
from scorecard.models import Measurable, Plant, ScoreEntry
from scorecard.units import unit_from_text
from scorecard.values_csv import load_values_csv
from tests.test_api import bearer

pytestmark = pytest.mark.django_db


@pytest.fixture
def cur_q(db):
    q = Quarter.for_calendar(timezone.localdate())
    Quarter.objects.update(is_current=False)
    q.is_current = True
    q.save()
    return q


@pytest.fixture
def pipeline(teams, member):
    return Measurable.objects.create(
        team=teams["ky"], title="Total Pipeline", owner=member, unit=Measurable.UNIT_CURRENCY,
        goal=Decimal("11000000"), goal_compare=Measurable.GTE, trailing=Measurable.TRAIL_AVG,
    )


# ---- formatting -------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, shown",
    [
        (11000000, "$11,000,000"),
        (Decimal("48213"), "$48,213"),
        (Decimal("48213.49"), "$48,213"),
        (Decimal("48213.50"), "$48,214"),
        (Decimal("0.5"), "$1"),
        (Decimal("0.49"), "$0"),
        (Decimal("2.5"), "$3"),
        (2.5, "$3"),
        (1234.5, "$1,235"),
        (Decimal("-1234.50"), "-$1,235"),
        (0, "$0"),
        (None, ""),
    ],
)
def test_format_dollars_whole_dollars_half_up(value, shown):
    assert format_dollars(value) == shown


def test_currency_measurable_displays_value_goal_and_average_in_dollars():
    m = Measurable(unit=Measurable.UNIT_CURRENCY, goal=Decimal("11000000"), goal_compare=Measurable.GTE)
    assert m.format_value(Decimal("48213.40")) == "$48,213"
    assert m.goal_display == "≥ $11,000,000"
    # Other units keep their own formatting.
    assert Measurable(unit=Measurable.UNIT_PERCENT).format_value(Decimal("72.5")) == "72.5%"
    assert Measurable(unit=Measurable.UNIT_NUMBER).format_value(Decimal("1200.5")) == "1,200.5"


@pytest.mark.parametrize(
    "text, unit",
    [
        ("$", "currency"), ("USD", "currency"), ("usd", "currency"), ("$M", "currency"), ("$k", "currency"),
        ("Dollars", "currency"), ("currency", "currency"), ("US$", "currency"),
        ("%", "percent"), ("percent", "percent"),
        ("yes/no", "yesno"), ("count", "number"), ("#", "number"), ("", "number"), ("tons", "number"),
    ],
)
def test_unit_from_text(text, unit):
    assert unit_from_text(text) == unit


def test_goals_written_as_dollars_parse():
    for raw in ("$11M", "USD 11M", "$11,000,000", "11M USD"):
        assert parse_goal(raw, "currency") == Decimal("11000000"), raw


# ---- everywhere dollars show -----------------------------------------------------------------

def test_scorecard_grid_panel_chart_and_raw_storage(as_user, member, teams, cur_q, pipeline):
    weeks = cur_q.weeks()
    this = [w for w in weeks if w <= timezone.localdate()]
    ScoreEntry.objects.create(measurable=pipeline, week_start=this[-2], value=Decimal("9876543.21"))
    ScoreEntry.objects.create(measurable=pipeline, week_start=this[-1], value=Decimal("48213.40"))
    c = as_user(member, teams["ky"])
    html = c.get("/scorecard/").content.decode()
    assert "≥ $11,000,000" in html
    assert 'value="$9,876,543"' in html and 'value="$48,213"' in html  # editable cells show dollars
    assert "9876543.21" not in html and "$48,213.40" not in html and "$9,876,543.21" not in html
    # Average of the two weeks (rounded once, at display time).
    assert "$4,962,378" in html

    panel = c.get(f"/scorecard/{pipeline.pk}/panel/", HTTP_HX_REQUEST="true").content.decode()
    assert "Goal ≥ $11,000,000" in panel or "Goal $11,000,000" in panel  # header and chart label
    assert "$48,213" in panel and "$9,876,543" in panel
    assert "<title>" in panel and ": $48,213</title>" in panel  # trend chart tooltip
    assert ".00" not in panel and "$48,213.4" not in panel
    # Axis ticks are round whole-dollar labels, not 1.2M-style shorthand.
    axis = [t.split("<")[0] for t in panel.split('text-anchor="end" font-size="10" fill="#8a8a8a">')[1:]]
    y_axis = axis[:-1]  # the last label on the end anchor is the final week
    assert y_axis and all(t.startswith("$") and (t == "$0" or "," in t) for t in y_axis)

    # Raw values are stored unchanged.
    assert ScoreEntry.objects.get(measurable=pipeline, week_start=this[-1]).value == Decimal("48213.40")


def test_dollar_average_rounds_once_not_twice(as_user, member, teams, cur_q, pipeline):
    a, b = cur_q.weeks()[:2]
    ScoreEntry.objects.create(measurable=pipeline, week_start=a, value=Decimal("1234.49"))
    ScoreEntry.objects.create(measurable=pipeline, week_start=b, value=Decimal("1234.50"))
    # 1234.495 is below the half-way point once rounded to a whole dollar.
    row = as_user(member, teams["ky"]).get("/scorecard/").context["rows"][0]
    assert row.trailing == "$1,234"


def test_editing_a_dollar_cell_accepts_what_the_cell_shows(as_user, member, teams, cur_q, pipeline):
    week = cur_q.weeks()[0]
    r = as_user(member, teams["ky"]).post(f"/scorecard/{pipeline.pk}/cell/{week.isoformat()}/", {"value": "$1,250,000"})
    assert r.status_code == 200 and 'value="$1,250,000"' in r.content.decode()
    assert ScoreEntry.objects.get().value == Decimal("1250000")


def test_dashboard_and_l10_scorecard_segment_show_dollars(as_user, member, teams, cur_q, pipeline):
    ScoreEntry.objects.create(measurable=pipeline, week_start=[w for w in cur_q.weeks() if w <= timezone.localdate()][-1], value=Decimal("11000000.4"))
    assert "$11,000,000" in as_user(member, teams["ky"]).get("/").content.decode()
    pipeline.plant = Plant.find("Kentucky")
    pipeline.save()
    meeting = Meeting.objects.create(team=teams["ky"], quarter=cur_q, date=timezone.localdate())
    meeting.attendees.add(member)
    seg = as_user(member, teams["ky"]).get(f"/meetings/{meeting.pk}/?s=scorecard").content.decode()
    assert "$11,000,000" in seg and "11000000.4" not in seg


def test_non_dollar_rows_are_unchanged(as_user, member, teams, cur_q):
    tons = Measurable.objects.create(team=teams["ky"], title="Tons", owner=member, goal=Decimal("1200"))
    ScoreEntry.objects.create(measurable=tons, week_start=cur_q.weeks()[0], value=Decimal("1200.5"))
    html = as_user(member, teams["ky"]).get("/scorecard/").content.decode()
    assert "≥ 1,200" in html and 'value="1200.5"' in html and "$" not in html.split("Tons")[1].split("</tr>")[0]


def test_api_display_fields_are_dollars_and_raw_values_stay_raw(member, teams, cur_q, pipeline):
    week = cur_q.weeks()[0]
    ScoreEntry.objects.create(measurable=pipeline, week_start=week, value=Decimal("48213.40"))
    _, raw = ApiToken.issue(member, "t")
    data = Client().get("/api/v1/scorecard", {"team": "kentucky"}, **bearer(raw)).json()["data"]
    m = data["measurables"][0]
    assert m["unit"] == "currency"
    assert m["goal"]["display"] == "≥ $11,000,000" and float(m["goal"]["value"]) == 11000000
    first = m["weeks"][0]
    assert first["display"] == "$48,213" and float(first["value"]) == 48213.40
    assert m["weeks"][1]["display"] == ""


# ---- source note ---------------------------------------------------------------------------

def test_source_note_shows_quietly_on_the_row_dashboard_and_panel(as_user, member, teams, cur_q):
    m = Measurable.objects.create(
        team=teams["ky"], title="Prelim Proposal Deal Value", owner=member, unit=Measurable.UNIT_CURRENCY,
        source="Filled weekly by assistant from Attio",
    )
    c = as_user(member, teams["ky"])
    assert "Filled weekly by assistant from Attio" in c.get("/scorecard/").content.decode()
    assert "Filled weekly by assistant from Attio" in c.get("/").content.decode()
    assert "Filled weekly by assistant from Attio" in c.get(f"/scorecard/{m.pk}/panel/", HTTP_HX_REQUEST="true").content.decode()


def test_source_note_can_be_edited(as_user, member, teams, cur_q, pipeline):
    r = as_user(member, teams["ky"]).post(f"/scorecard/{pipeline.pk}/edit/", {
        "title": "Total Pipeline", "owner": member.pk, "unit": "currency", "goal_compare": "gte", "goal": "11000000",
        "trailing": "avg", "source": "Filled weekly by assistant from Attio", "sort": 0,
    })
    assert r.status_code == 302
    pipeline.refresh_from_db()
    assert pipeline.source == "Filled weekly by assistant from Attio"


# ---- importer -----------------------------------------------------------------------------

def _metric(pk, name, unit, source=None, goal="", facility=None, direction="up"):
    fields = {"name": name, "facility": facility, "unit": unit, "sort": pk, "active": True, "owner": "", "goal": goal, "direction": direction}
    if source:
        fields["source"] = source
    return {"model": "core.scorecardmetric", "pk": pk, "fields": fields}


EXPORT = [
    {"model": "core.facility", "pk": 1, "fields": {"name": "Company", "short_code": "CO", "sort": 0}},
    {"model": "core.facility", "pk": 2, "fields": {"name": "Kentucky", "short_code": "KY", "sort": 1}},
    _metric(1, "Total Pipeline", "$M", goal="$11M"),
    _metric(2, "Revenue Invoiced", "USD"),
    _metric(3, "Prelim quotes sent", "count", source="iquote_quotes"),
    _metric(4, "R&D formulas sent", "count", source="iquote_rd"),
    _metric(5, "Prelim Proposal Deal Value", "$", source="attio_prelim"),
    _metric(6, "R&D Stage Deal Value", "$", source="attio_rd"),
    _metric(7, "Final Proposal Deal Value", "$", source="attio_final"),
    _metric(8, "OEE", "%", goal="40%", facility=2),
]


def test_importer_reads_dollar_units_and_labels_the_auto_filled_rows():
    BattlePlannerImporter(EXPORT).run()
    by = {m.title: m for m in Measurable.objects.all()}
    assert by["Total Pipeline"].unit == "currency" and by["Total Pipeline"].goal == Decimal("11000000")
    assert by["Revenue Invoiced"].unit == "currency"
    assert by["OEE"].unit == "percent" and by["OEE"].source == ""
    assert by["Prelim quotes sent"].source == "Filled weekly by assistant from iQuote"
    assert by["R&D formulas sent"].source == "Filled weekly by assistant from iQuote"
    for title in ("Prelim Proposal Deal Value", "R&D Stage Deal Value", "Final Proposal Deal Value"):
        assert by[title].source == "Filled weekly by assistant from Attio" and by[title].unit == "currency"


def test_importer_keeps_a_source_note_someone_edited():
    BattlePlannerImporter(EXPORT).run()
    Measurable.objects.filter(title="Prelim Proposal Deal Value").update(source="Posted by Ben each Monday")
    BattlePlannerImporter(EXPORT, refresh=True).run()
    assert Measurable.objects.get(title="Prelim Proposal Deal Value").source == "Posted by Ben each Monday"


def test_backfill_migration_fixes_units_and_labels_existing_rows(teams):
    import importlib

    from django.apps import apps

    backfill = importlib.import_module("scorecard.migrations.0003_backfill_currency_and_source").backfill
    usd = Measurable.objects.create(team=teams["ky"], title="Revenue", legacy={"unit": "USD"})
    attio = Measurable.objects.create(team=teams["ky"], title="Deal value", unit="currency", legacy={"unit": "$", "source": "attio_rd"})
    typed = Measurable.objects.create(team=teams["ky"], title="Tons", legacy={"unit": "count"})
    noted = Measurable.objects.create(team=teams["ky"], title="Final", source="Mine", legacy={"source": "attio_final"})
    backfill(apps, None)
    for m in (usd, attio, typed, noted):
        m.refresh_from_db()
    assert usd.unit == "currency" and attio.source == "Filled weekly by assistant from Attio"
    assert typed.unit == "number" and typed.source == "" and noted.source == "Mine"


# ---- supplementary CSV --------------------------------------------------------------------

CSV = """metric name,facility,week_start,value
Prelim Proposal Deal Value,,2026-11-02,"$1,250,000.40"
Prelim Proposal Deal Value,,2026-11-11,1300000
Prelim quotes sent,,2026-11-02,14
OEE,Kentucky,2026-11-02,41.5%
OEE,Kentucky,2026-11-09,
Nope,,2026-11-02,5
OEE,Elsewhere,2026-11-02,5
OEE,Kentucky,not-a-date,5
OEE,Kentucky,2026-11-16,lots
"""


@pytest.fixture
def csv_world(db):
    BattlePlannerImporter(EXPORT).run()


def _week(day):
    return monday_of(dt.date.fromisoformat(day))


def test_values_csv_upserts_by_name_and_facility(csv_world):
    first = load_values_csv(CSV)
    c = first.counts
    assert (c["created"], c["updated"], c["unchanged"]) == (4, 0, 0)
    assert c["skipped"] == 5
    prelim = Measurable.objects.get(title="Prelim Proposal Deal Value")
    assert ScoreEntry.objects.get(measurable=prelim, week_start=_week("2026-11-02")).value == Decimal("1250000.40")
    # A date mid-week lands on its Monday.
    assert ScoreEntry.objects.get(measurable=prelim, week_start=_week("2026-11-09")).value == Decimal("1300000")
    oee = Measurable.objects.get(title="OEE")
    assert ScoreEntry.objects.get(measurable=oee, week_start=_week("2026-11-02")).value == Decimal("41.5")
    notes = " | ".join(first.notes)
    assert "no measurable 'Nope'" in notes and "unknown facility 'Elsewhere'" in notes
    assert "needs a metric and a readable week_start" in notes and "can't read 'lots'" in notes

    again = load_values_csv(CSV)
    assert (again.counts["created"], again.counts["updated"], again.counts["unchanged"]) == (0, 0, 4)
    assert ScoreEntry.objects.count() == 4

    changed = load_values_csv("metric,facility,week_start,value\nPrelim Proposal Deal Value,,2026-11-02,2000000\n")
    assert changed.counts["updated"] == 1 and ScoreEntry.objects.count() == 4
    assert ScoreEntry.objects.get(measurable=prelim, week_start=_week("2026-11-02")).value == Decimal("2000000")


def test_values_csv_blank_value_never_clears_and_headers_are_flexible(csv_world):
    load_values_csv("Metric,Team,Week,Value\nOEE,KY,11/02/2026,40\n")
    load_values_csv("Metric,Team,Week,Value\nOEE,KY,11/02/2026,\n")
    assert ScoreEntry.objects.get().value == Decimal("40")


def test_values_csv_needs_the_right_columns(csv_world):
    with pytest.raises(ValueError, match="value"):
        load_values_csv("metric,week_start\nOEE,2026-11-02\n")


def test_values_csv_name_on_several_teams_needs_a_facility(csv_world):
    other = Team.objects.create(name="Le Roy", short_code="LR", sort=2)
    Measurable.objects.create(team=other, plant=Plant.find("Le Roy"), title="OEE", unit="percent")
    res = load_values_csv("metric,facility,week_start,value\nOEE,,2026-11-02,5\n")
    assert res.counts["skipped"] == 1 and "several measurables" in res.notes[0]
    assert load_values_csv("metric,facility,week_start,value\nOEE,Le Roy,2026-11-02,5\n").counts["created"] == 1


def test_command_loads_the_csv_alone_or_after_an_export(tmp_path, csv_world):
    csv_file = tmp_path / "values.csv"
    csv_file.write_text(CSV, encoding="utf-8")
    out = StringIO()
    call_command("import_battle_planner", values_csv=str(csv_file), stdout=out)
    text = out.getvalue()
    assert "4 created, 0 updated, 0 unchanged, 5 skipped" in text and "Done." in text

    export = tmp_path / "export.json"
    export.write_text(json.dumps(EXPORT), encoding="utf-8")
    out = StringIO()
    call_command("import_battle_planner", str(export), values_csv=str(csv_file), stdout=out)
    assert "0 created, 0 updated, 4 unchanged" in out.getvalue()

    with pytest.raises(CommandError):
        call_command("import_battle_planner")
    with pytest.raises(CommandError):
        call_command("import_battle_planner", values_csv=str(tmp_path / "missing.csv"))


# ---- API / MCP write tool ----------------------------------------------------------------

def _post(raw, path, body):
    return Client().post(path, json.dumps(body), content_type="application/json", **bearer(raw))


def test_set_value_by_name_upserts_a_week(admin, member, teams, cur_q, pipeline):
    _, raw = ApiToken.issue(member, "assistant")
    week = cur_q.weeks()[0].isoformat()
    r = _post(raw, "/api/v1/measurables/values", {"measurable": "total pipeline", "value": "$11,250,000.60", "week": week})
    assert r.status_code == 200, r.content
    data = r.json()["data"]
    assert data["created"] is True and data["measurable_id"] == pipeline.pk
    assert data["display"] == "$11,250,001" and data["on_goal"] is True and float(data["value"]) == 11250000.60

    r = _post(raw, "/api/v1/measurables/values", {"measurable": str(pipeline.pk), "value": 10000000, "week": week})
    data = r.json()["data"]
    assert data["created"] is False and data["display"] == "$10,000,000" and data["on_goal"] is False
    assert ScoreEntry.objects.count() == 1
    assert ScoreEntry.objects.get().value == Decimal("10000000")

    r = _post(raw, "/api/v1/measurables/values", {"measurable_id": pipeline.pk, "value": 9, "week": week})
    assert r.status_code == 200 and ScoreEntry.objects.get().value == 9
    r = _post(raw, f"/api/v1/measurables/{pipeline.pk}/values", {"value": None, "week": week})
    assert r.status_code == 200 and not ScoreEntry.objects.exists()


def test_set_value_by_name_errors_are_clear(member, other, teams, cur_q, pipeline):
    pipeline.plant = Plant.find("Kentucky")
    pipeline.save()
    Measurable.objects.create(team=teams["lr"], plant=Plant.find("Le Roy"), title="Total Pipeline", owner=other, unit=Measurable.UNIT_CURRENCY)
    _, raw = ApiToken.issue(member, "assistant")
    r = _post(raw, "/api/v1/measurables/values", {"measurable": "Total Pipeline", "value": 1})
    assert r.status_code == 400 and "kentucky" in r.json()["error"] and "le-roy" in r.json()["error"]
    r = _post(raw, "/api/v1/measurables/values", {"measurable": "Total Pipeline", "plant": "kentucky", "value": 1})
    assert r.status_code == 200 and r.json()["data"]["plant"] == "Kentucky"
    assert _post(raw, "/api/v1/measurables/values", {"measurable": "Total Pipeline", "plant": "mars", "value": 1}).status_code == 400
    assert _post(raw, "/api/v1/measurables/values", {"measurable": "No such row", "value": 1}).status_code == 400
    assert _post(raw, "/api/v1/measurables/values", {"value": 1}).status_code == 400
    assert _post(raw, "/api/v1/measurables/values", {"measurable": "Total Pipeline", "plant": "kentucky", "value": "lots"}).status_code == 400


def test_set_value_by_name_respects_ownership_and_read_only_tokens(member, ky_peer, admin, teams, cur_q, pipeline):
    _, peer = ApiToken.issue(ky_peer, "peer")
    r = _post(peer, "/api/v1/measurables/values", {"measurable": "Total Pipeline", "value": 1})
    assert r.status_code == 403 and not ScoreEntry.objects.exists()
    _, boss = ApiToken.issue(admin, "admin")
    assert _post(boss, "/api/v1/measurables/values", {"measurable": "Total Pipeline", "value": 1}).status_code == 200
    _, ro = ApiToken.issue(member, "ro", can_write=False)
    assert _post(ro, "/api/v1/measurables/values", {"measurable": "Total Pipeline", "value": 2}).status_code == 403


def test_mcp_tool_takes_a_name_and_audits(member, teams, cur_q, pipeline):
    from api.models import AuditLog

    _, raw = ApiToken.issue(member, "Claude")
    week = cur_q.weeks()[0].isoformat()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "set_measurable_value", "arguments": {"measurable": "Total Pipeline", "value": 12000000, "week": week}}}
    res = Client().post("/mcp", json.dumps(body), content_type="application/json", **bearer(raw)).json()["result"]
    assert not res["isError"] and res["structuredContent"]["display"] == "$12,000,000"
    log = AuditLog.objects.get(action="scorecard.set_value")
    assert "$12,000,000" in log.summary and log.source == AuditLog.MCP
    tools = {t["name"]: t for t in Client().post(
        "/mcp", json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}), content_type="application/json", **bearer(raw)
    ).json()["result"]["tools"]}
    props = tools["set_measurable_value"]["inputSchema"]["properties"]
    assert {"measurable", "measurable_id", "team", "value", "week"} <= set(props)
    assert tools["set_measurable_value"]["inputSchema"]["required"] == []
