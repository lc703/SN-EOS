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
