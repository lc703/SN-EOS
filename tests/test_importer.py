import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from core.models import LegacyRecord, Quarter, Team, User
from issues.models import Issue
from meetings.models import Meeting, MeetingRating
from people.models import OneOnOne, PeopleReview, SuccessStatement
from rocks.models import Milestone, Rock
from scorecard.models import Measurable
from todos.models import Todo
from vision.models import VTO, CoreValue, Seat

FIXTURE = Path(__file__).parent / "fixtures" / "battle_planner_sample.json"
MODELS = [Team, User, Quarter, CoreValue, Rock, Milestone, Issue, Todo, Measurable, Seat, SuccessStatement, OneOnOne,
          PeopleReview, Meeting, MeetingRating, LegacyRecord]

pytestmark = pytest.mark.django_db


def run_import(*args):
    out = StringIO()
    call_command("import_battle_planner", str(FIXTURE), *args, stdout=out)
    return out.getvalue()


def counts():
    return {m.__name__: m.objects.count() for m in MODELS}


def test_import_maps_core_entities():
    output = run_import()
    company, ky = Team.objects.get(name="Company"), Team.objects.get(name="Kentucky")
    assert company.is_leadership and not ky.is_leadership
    assert set(ky.members.values_list("email", flat=True)) == {"alex@steuartnutrition.com", "drew@steuartnutrition.com"}

    alex = User.objects.get(email="alex@steuartnutrition.com")
    assert alex.is_admin and not alex.has_usable_password()
    assert User.objects.get(email="drew@steuartnutrition.com").home_team == ky
    assert Quarter.objects.get(name="Q4 2026").weeks()[0].isoformat() == "2026-09-28"
    assert "Imported" in output and "Done." in output


def test_rock_status_comes_from_latest_weekly_status():
    run_import()
    revenue = Rock.objects.get(title="Close new revenue")
    assert revenue.status == Rock.OFF_TRACK  # latest rockstatus is red although current_rag says green
    assert revenue.is_company and revenue.owner.name == "Alex Admin"
    assert [h["rag"] for h in revenue.legacy["status_history"]] == ["green", "red"]
    assert Rock.objects.get(title="Install new line").status == Rock.ON_TRACK  # yellow -> on track
    assert Rock.objects.get(title="Hire QA lead").status == Rock.DONE
    assert list(revenue.milestones.values_list("title", "done")) == [("Send 10 proposals", True), ("Close 2 deals", False)]


def test_issues_and_commitments():
    run_import()
    solved = Issue.objects.get(title="Metal detector is unreliable")
    assert solved.status == Issue.SOLVED
    top = Issue.objects.get(title="Changeovers take too long")
    assert top.is_open and top.priority == 1
    parked = Issue.objects.get(title="Consider a third plant")
    assert parked.is_open and parked.horizon == Issue.LONG

    miss = Todo.objects.get(title="Send quote to customer")
    assert not miss.done and "Missed: Costs were high" in miss.notes
    assert miss.rock.title == "Close new revenue" and miss.team.name == "Company"
    hit = Todo.objects.get(title="Fix metal detector")
    assert hit.done and hit.done_at and hit.issue == solved and hit.team.name == "Kentucky"
    assert not Todo.objects.get(title="Draft hiring plan").done


def test_measurables_vto_values_and_chart():
    run_import()
    units = dict(Measurable.objects.values_list("title", "unit"))
    assert units == {"OEE": "percent", "Leads pursued": "number", "Proposal system followed": "yesno"}
    assert Measurable.objects.get(title="Leads pursued").team.is_leadership

    vto = VTO.load()
    assert vto.purpose == "Make healthy products."
    assert vto.ten_year_target == "1 million happy customers by 2030."
    assert vto.uniques.splitlines() == ["Speed", "Quality", "Formats"]
    assert vto.three_year_measurables.startswith("Double revenue.")
    assert vto.legacy["strategy_house"]["major_business_challenge"] == "Grow faster."
    assert vto.legacy["boxes"][0]["dri"] == "Alex Admin"

    assert list(CoreValue.objects.values_list("name", flat=True)) == ["Own It", "Be Kind"]
    lead = Seat.objects.get(title="Line Lead")
    assert lead.parent.title == "Plant Manager" and lead.parent.person.name == "Drew Plant"
    assert lead.person.name == "Fran Floor"  # matched by name when the seat had no linked user


def test_one_on_ones_people_analyzer_and_meetings():
    run_import()
    fran = User.objects.get(email="fran@pending.invalid")
    one = OneOnOne.objects.get(person=fran)
    assert one.manager.name == "Drew Plant"  # from the accountability chart
    assert "The line hits its OEE target" in one.notes and "OEE was low" in one.notes
    assert "Be Kind: Watch tone" in one.notes
    review = PeopleReview.objects.get(person=fran)
    assert dict(review.ratings.values_list("value__name", "rating")) == {"Own It": "+", "Be Kind": "+/-"}

    meeting = Meeting.objects.get()
    assert meeting.team.name == "Kentucky" and meeting.is_concluded
    assert meeting.attendees.count() == 2
    assert "Drew Plant: New line ran clean" in meeting.segue_notes
    ratings = dict(meeting.ratings.values_list("user__name", "rating"))
    assert ratings == {"Alex Admin": 9, "Drew Plant": 6}  # green=10 yellow=7 red=4, averaged
    assert meeting.average_rating == 7.5


def test_unmapped_models_are_archived_and_reported():
    output = run_import()
    assert set(LegacyRecord.objects.values_list("model", flat=True)) == {"core.offsite", "core.swotitem", "core.meetingcriterion"}
    assert "Not mapped" in output and "core.swotitem" in output


def test_import_is_idempotent():
    run_import()
    first = counts()
    output = run_import()
    assert counts() == first
    assert "created" not in output.split("Not mapped")[0]
    run_import("--refresh")
    assert counts() == first


def test_import_keeps_app_edits_unless_refresh():
    run_import()
    rock = Rock.objects.get(title="Close new revenue")
    rock.status = Rock.DONE
    rock.save()
    run_import()
    rock.refresh_from_db()
    assert rock.status == Rock.DONE
    run_import("--refresh")
    rock.refresh_from_db()
    assert rock.status == Rock.OFF_TRACK


def test_existing_user_is_linked_by_email():
    pre = User.objects.create_user(email="ALEX@steuartnutrition.com", name="")
    run_import()
    pre.refresh_from_db()
    assert pre.legacy_id == 1 and pre.name == "Alex Admin"
    assert User.objects.filter(email="alex@steuartnutrition.com").count() == 1


def test_bad_input_errors(tmp_path):
    with pytest.raises(CommandError):
        call_command("import_battle_planner", str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(CommandError):
        call_command("import_battle_planner", str(bad))


SCORECARD_ROWS = [
    {"model": "core.facility", "pk": 1, "fields": {"name": "Company", "short_code": "CO", "sort": 0}},
    {"model": "core.facility", "pk": 2, "fields": {"name": "Kentucky", "short_code": "KY", "sort": 1}},
    {"model": "core.user", "pk": 1, "fields": {"email": "ben@steuartnutrition.com", "name": "Ben Steuart", "role": "admin", "facility": 1}},
    {"model": "core.user", "pk": 5, "fields": {"email": "jm@steuartnutrition.com", "name": "Jacob Miller", "facility": 2}},
    {"model": "core.user", "pk": 7, "fields": {"email": "joel@steuartnutrition.com", "name": "Joel Senecal-Moseley", "facility": 2}},
    {"model": "core.quarter", "pk": 1, "fields": {"name": "Q4 2026", "start_date": "2026-10-01", "end_date": "2026-12-31", "is_active": True}},
    {"model": "core.scorecardmetric", "pk": 1, "fields": {"name": "OEE", "facility": 2, "unit": "%", "sort": 1, "active": True,
                                                         "owner": "JM", "goal": "40%", "direction": "up", "source": "manual"}},
    {"model": "core.scorecardmetric", "pk": 9, "fields": {"name": "Quality Check OOS", "facility": 2, "unit": "count", "sort": 5,
                                                         "active": True, "owner": "JSM", "goal": "10", "direction": "down", "source": "manual"}},
    {"model": "core.scorecardmetric", "pk": 17, "fields": {"name": "Total Pipeline", "facility": None, "unit": "$", "sort": 13,
                                                          "active": True, "owner": "BS", "goal": "$11M", "direction": "up", "source": "manual"}},
    {"model": "core.scorecardmetric", "pk": 21, "fields": {"name": "Revenue Invoiced", "facility": None, "unit": "$", "sort": 20,
                                                          "active": True, "owner": "ZZ", "goal": "", "direction": "up", "source": "manual"}},
    {"model": "core.scorecardmetric", "pk": 4, "fields": {"name": "Leads pursued", "facility": None, "unit": "count", "sort": 3,
                                                         "active": False, "owner": "", "goal": "5", "direction": "", "source": "manual"}},
    {"model": "core.scorecardmetric", "pk": 23, "fields": {"name": "Prelim Deal Value", "facility": None, "unit": "$", "sort": 14,
                                                          "active": True, "owner": "BS", "goal": "", "direction": "up", "source": "attio_prelim"}},
    {"model": "core.scorecardentry", "pk": 1, "fields": {"metric": 1, "week_start": "2026-09-28", "value": "25.7%", "entered_by": 1}},
    {"model": "core.scorecardentry", "pk": 2, "fields": {"metric": 1, "week_start": "2026-11-11", "value": "51.8%", "entered_by": 1}},
    {"model": "core.scorecardentry", "pk": 3, "fields": {"metric": 9, "week_start": "2026-10-05", "value": "41", "entered_by": None}},
    {"model": "core.scorecardentry", "pk": 4, "fields": {"metric": 21, "week_start": "2026-10-05", "value": "$215,316.78", "entered_by": 1}},
    {"model": "core.scorecardentry", "pk": 5, "fields": {"metric": 21, "week_start": "2026-10-12", "value": "-$116,000", "entered_by": 1}},
    {"model": "core.scorecardentry", "pk": 6, "fields": {"metric": 9, "week_start": "2026-10-12", "value": "?", "entered_by": 1}},
]


def _import_rows(rows, refresh=False):
    from core.importer import BattlePlannerImporter

    importer = BattlePlannerImporter(json.loads(json.dumps(rows)), refresh=refresh)
    return importer, importer.run()


def test_scorecard_metrics_map_owner_goal_direction():
    from decimal import Decimal

    importer, _ = _import_rows(SCORECARD_ROWS)
    oee = Measurable.objects.get(legacy_id=1)
    assert oee.team.name == "Kentucky" and oee.unit == "percent" and oee.sort == 1
    assert oee.owner.name == "Jacob Miller" and oee.goal == Decimal("40") and oee.goal_compare == Measurable.GTE
    oos = Measurable.objects.get(legacy_id=9)
    assert oos.owner.name == "Joel Senecal-Moseley" and oos.goal == 10 and oos.goal_compare == Measurable.LTE
    pipe = Measurable.objects.get(legacy_id=17)
    assert pipe.team.is_leadership and pipe.unit == "currency" and pipe.goal == Decimal("11000000")
    assert pipe.owner.name == "Ben Steuart"
    rev = Measurable.objects.get(legacy_id=21)
    assert rev.owner is None and rev.goal is None and rev.legacy["owner"] == "ZZ"
    leads = Measurable.objects.get(legacy_id=4)
    assert not leads.active and leads.goal is None  # no direction = no color in the old app
    notes = " ".join(importer.notes)
    assert "ZZ" in notes and "Prelim Deal Value" in notes and "?" in notes


def test_scorecard_values_land_in_quarter_grid_with_colors(admin):
    from decimal import Decimal

    from scorecard.views import build_rows

    _, stats = _import_rows(SCORECARD_ROWS)
    assert stats["Scorecard values"] == {"created": 5, "skipped": 1}
    oee = Measurable.objects.get(legacy_id=1)
    weeks = Quarter.objects.get(name="Q4 2026").weeks()
    assert sorted(e.week_start for e in oee.entries.all()) == [weeks[0], weeks[6]]  # Wed 11/11 -> Mon 11/09
    row = build_rows([oee, Measurable.objects.get(legacy_id=9)], weeks, admin)
    assert row[0].cells[0].state == "red" and row[0].cells[6].state == "green"
    assert row[0].cells[0].display == "25.7%"
    assert row[1].cells[1].state == "red"  # 41 > goal 10, lower is better
    rev = Measurable.objects.get(legacy_id=21)
    assert list(rev.entries.values_list("value", flat=True)) == [Decimal("215316.78"), Decimal("-116000")]
    assert oee.entries.first().updated_by.email == "ben@steuartnutrition.com"


def test_scorecard_reimport_is_idempotent_and_refresh_updates():
    from decimal import Decimal

    from scorecard.models import ScoreEntry

    _import_rows(SCORECARD_ROWS)
    before = ScoreEntry.objects.count()
    entry = ScoreEntry.objects.get(measurable__legacy_id=1, week_start="2026-09-28")
    entry.value = Decimal("99")
    entry.save()
    _, stats = _import_rows(SCORECARD_ROWS)
    assert ScoreEntry.objects.count() == before and stats["Scorecard values"]["unchanged"] == 5
    entry.refresh_from_db()
    assert entry.value == Decimal("99")  # app edits survive a plain re-run
    rows = json.loads(json.dumps(SCORECARD_ROWS))
    rows[6]["fields"]["goal"] = "45%"
    _, stats = _import_rows(rows, refresh=True)
    entry.refresh_from_db()
    assert entry.value == Decimal("25.7") and stats["Scorecard values"]["updated"] == 1
    assert Measurable.objects.get(legacy_id=1).goal == Decimal("45")
    assert ScoreEntry.objects.count() == before
