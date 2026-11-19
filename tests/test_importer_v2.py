"""Battle Planner data that V1 parked in legacy JSON now lands in real models."""

import importlib
import json
from io import StringIO
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command

from core.importer import BattlePlannerImporter
from core.models import LegacyRecord
from people.models import OneOnOne, OneOnOneScore
from planning.models import Session, SessionItem
from rocks.models import Rock, RockUpdate
from vision.models import VTO, Goal, Seat

FIXTURE = Path(__file__).parent / "fixtures" / "battle_planner_sample.json"
pytestmark = pytest.mark.django_db


def run_import(*args):
    out = StringIO()
    call_command("import_battle_planner", str(FIXTURE), *args, stdout=out)
    return out.getvalue()


def rows_with(*extra):
    rows = json.loads(FIXTURE.read_text())
    return rows + list(extra)


def test_seat_status_and_agency_are_real_fields():
    rows = rows_with({"model": "core.seat", "pk": 3, "fields": {"facility": 2, "parent": 1, "title": "QA Tech", "person_name": "",
                                                                "person": None, "status": "red", "responsibilities": "", "agency": True, "sort": 2}})
    BattlePlannerImporter(rows).run()
    assert Seat.objects.get(title="Plant Manager").status == Seat.FILLED
    assert Seat.objects.get(title="Line Lead").status == Seat.FUTURE
    qa = Seat.objects.get(title="QA Tech")
    assert qa.status == Seat.OPEN and qa.is_agency and qa.effective_status == Seat.OPEN


def test_weekly_rock_status_history_becomes_rock_updates():
    run_import()
    rock = Rock.objects.get(title="Close new revenue")
    ups = list(rock.updates.order_by("week_start").values_list("week_start", "rag", "recovery_plan"))
    assert [(str(w), r) for w, r, _ in ups] == [("2026-10-05", "green"), ("2026-10-12", "red")]
    assert ups[1][2] == "More calls"
    assert rock.updates.get(rag="red").author.name == "Alex Admin"
    assert rock.rag == "red" and rock.status == Rock.OFF_TRACK
    strip = rock.week_strip()
    assert len(strip) == 13 and strip[1][1].rag == "green" and strip[2][1].rag == "red"


def test_one_on_one_grid_scores_per_statement_and_value():
    run_import()
    one = OneOnOne.objects.get()
    assert one.highlight == "Good week" and one.completed_at is not None
    grid = {(s.statement.text if s.statement else s.value.name): (s.rag, s.note) for s in one.scores.select_related("statement", "value")}
    assert grid == {"The line hits its OEE target": ("red", "OEE was low"), "Own It": ("green", ""), "Be Kind": ("yellow", "Watch tone")}
    assert one.struggling


def test_strategy_house_folds_into_vto_goals():
    run_import()
    vto = VTO.load()
    assert vto.niche == "Grow faster."
    goal = Goal.objects.get()
    assert goal.title == "Win deals" and goal.strategy == "Focus" and goal.tactic_list == ["Call"]
    assert goal.owner.name == "Alex Admin" and str(goal.due_date) == "2026-12-31"
    assert Rock.objects.get(title="Close new revenue").goal == goal


def test_offsites_become_quarterly_sessions():
    rows = rows_with(
        {"model": "core.fourwhatsitem", "pk": 1, "fields": {"offsite": 1, "kind": "broken", "text": "Handoffs", "author": 3}},
        {"model": "core.offsitelesson", "pk": 1, "fields": {"offsite": 1, "title": "Hire earlier", "body": "Lead time", "author": 1, "sort": 0}},
        {"model": "core.missioneval", "pk": 1, "fields": {"offsite": 1, "statement_key": "visible", "rag": "yellow", "note": ""}},
    )
    BattlePlannerImporter(rows).run()
    session = Session.objects.get()
    assert session.team.name == "Kentucky" and session.kind == Session.QUARTERLY and session.is_concluded
    items = {(i.step, i.kind, i.text) for i in session.items.all()}
    assert ("swot", "swot_strength", "Strong team") in items
    assert ("segue", "not_working", "Broken: Handoffs") in items
    assert ("review", "lesson", "Hire earlier — Lead time") in items
    assert session.items.get(kind="vto_check").rag == "yellow"
    # The raw rows stay in LegacyRecord as an audit copy.
    assert LegacyRecord.objects.filter(model="core.swotitem").exists()
    count = SessionItem.objects.count()
    BattlePlannerImporter(rows).run()
    BattlePlannerImporter(rows, refresh=True).run()
    assert SessionItem.objects.count() == count and Session.objects.count() == 1


def test_new_models_are_idempotent():
    run_import()
    counts = (RockUpdate.objects.count(), OneOnOneScore.objects.count(), Goal.objects.count(), Session.objects.count())
    run_import()
    run_import("--refresh")
    assert (RockUpdate.objects.count(), OneOnOneScore.objects.count(), Goal.objects.count(), Session.objects.count()) == counts


def test_red_update_needs_recovery_plan():
    from django.core.exceptions import ValidationError

    run_import()
    rock = Rock.objects.get(title="Install new line")
    update = RockUpdate(rock=rock, week_start=rock.quarter.weeks()[3], rag="red")
    with pytest.raises(ValidationError):
        update.full_clean()


def _migration(app, name):
    return importlib.import_module(f"{app}.migrations.{name}")


def test_backfill_migrations_convert_v1_legacy_json(teams, quarter):
    """A database imported by V1 (status/history/scores only in legacy JSON) is upgraded in place."""
    from core.models import User
    from people.models import SuccessStatement
    from vision.models import CoreValue

    alex = User.objects.create_user(email="alex@steuartnutrition.com", name="Alex Admin")
    seat = Seat.objects.create(title="Open seat", team=teams["ky"], legacy={"status": "red", "agency": True})
    rock = Rock.objects.create(quarter=quarter, team=teams["ky"], title="R", legacy={"status_history": [
        {"week_start": "2026-10-05", "rag": "green", "note": "ok", "recovery_plan": "", "author": "Alex Admin"},
        {"week_start": "2026-10-12", "rag": "red", "note": "late", "recovery_plan": "push", "author": "Alex Admin"},
    ]})
    st = SuccessStatement.objects.create(person=alex, text="Ship", legacy_id=10)
    cv = CoreValue.objects.create(name="Own It", legacy_id=1)
    one = OneOnOne.objects.create(person=alex, notes="Highlight: Big win\n\nmore", legacy={
        "scores": {"ss10": {"rag": "red", "note": "slow"}, "cv1": {"rag": "green", "note": ""}}, "completed_at": "2026-10-01T16:00:00Z"})
    vto = VTO.load()
    vto.legacy = {"strategy_house": {"major_business_challenge": "Niche!", "targets": [{"label": "Revenue", "value": "$1M"}]},
                  "boxes": [{"kind": "opportunity", "statement": "Win", "strategy": "S", "tactics": ["T1"], "dri": "Alex Admin", "due_date": "2026-12-31"}]}
    vto.save()
    LegacyRecord.objects.create(model="core.offsite", legacy_id=7, data={"facility": None, "quarter": None, "date": "2026-10-01", "status": "complete"})
    LegacyRecord.objects.create(model="core.swotitem", legacy_id=1, data={"offsite": 7, "kind": "threat", "text": "Tariffs", "author": None})

    _migration("vision", "0003_backfill_from_legacy").forwards(django_apps, None)
    _migration("rocks", "0003_backfill_rock_updates").forwards(django_apps, None)
    _migration("people", "0003_backfill_scores").forwards(django_apps, None)
    _migration("planning", "0002_backfill_offsites").forwards(django_apps, None)

    seat.refresh_from_db()
    assert seat.status == Seat.OPEN and seat.is_agency
    assert list(rock.updates.order_by("week_start").values_list("rag", flat=True)) == ["green", "red"]
    rock.refresh_from_db()
    assert rock.updates.get(rag="red").author == alex
    one.refresh_from_db()
    assert one.highlight == "Big win" and one.completed_at
    assert {(s.statement_id, s.value_id, s.rag) for s in one.scores.all()} == {(st.pk, None, "red"), (None, cv.pk, "green")}
    vto.refresh_from_db()
    assert vto.niche == "Niche!" and vto.one_year_measurables == "$1M Revenue"
    assert Goal.objects.get().owner == alex
    session = Session.objects.get(legacy_id=7)
    assert session.team == teams["company"] and session.items.get().kind == "swot_threat"
