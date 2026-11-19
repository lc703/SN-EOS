import json
from io import StringIO
from pathlib import Path

import pytest
from django.db import models
from django.core.management import CommandError, call_command

from core.models import LegacyRecord, Quarter, Team, User
from issues.models import Issue
from meetings.models import Meeting, MeetingRating
from people.models import ConversationScore, OneOnOne, PeopleReview, SuccessStatement
from planning.models import Session, SessionItem
from rocks.models import Milestone, Rock, RockUpdate
from scorecard.models import Measurable
from todos.models import Todo
from vision.models import VTO, CoreValue, Seat

FIXTURE = Path(__file__).parent / "fixtures" / "battle_planner_sample.json"
MODELS = [Team, User, Quarter, CoreValue, Rock, Milestone, Issue, Todo, Measurable, Seat, SuccessStatement, OneOnOne,
          PeopleReview, Meeting, MeetingRating, LegacyRecord, RockUpdate, ConversationScore, Session, SessionItem]

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
    updates = list(revenue.updates.order_by("week_start").values_list("week_start", "color", "recovery_plan"))
    assert [(w.isoformat(), c, r) for w, c, r in updates] == [("2026-10-05", "green", ""), ("2026-10-12", "red", "More calls")]
    assert revenue.updates.get(color="red").author.name == "Alex Admin"
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
    assert vto.one_year_measurables.splitlines() == ["On-time delivery", "Revenue: $1M"]
    assert vto.legacy["strategy_house"]["lessons"][0]["title"] == "Lesson one"

    assert list(CoreValue.objects.values_list("name", flat=True)) == ["Own It", "Be Kind"]
    lead = Seat.objects.get(title="Line Lead")
    assert lead.parent.title == "Plant Manager" and lead.parent.person.name == "Drew Plant"
    assert lead.person.name == "Fran Floor"  # matched by name when the seat had no linked user
    assert lead.status == Seat.FUTURE and not lead.agency
    tech = Seat.objects.get(title="Maintenance Tech")
    assert tech.status == Seat.OPEN and tech.agency and tech.is_open
    assert Seat.objects.get(title="Plant Manager").status == Seat.FILLED


def test_strategy_house_lands_on_vto_issues_list():
    run_import()
    long_term = Issue.objects.filter(horizon=Issue.LONG, team__is_leadership=True)
    titles = set(long_term.values_list("title", flat=True))
    assert {"Grow faster.", "Win deals", "Look at a second warehouse"} <= titles
    box = long_term.get(title="Win deals")
    assert box.owner.name == "Alex Admin" and "Strategy: Focus" in box.description and "- Call" in box.description
    assert box.legacy["source"] == "core.box:1"


def test_one_on_ones_people_analyzer_and_meetings():
    run_import()
    fran = User.objects.get(email="fran@pending.invalid")
    one = OneOnOne.objects.get(person=fran)
    assert one.manager.name == "Drew Plant"  # from the accountability chart
    assert one.highlight == "Good week" and one.completed_at is not None and one.quarter.name == "Q4 2026"
    grid = {(str(sc.subject), sc.color, sc.note) for sc in one.scores.all()}
    assert grid == {("Own It", "green", ""), ("Be Kind", "yellow", "Watch tone"), ("The line hits its OEE target", "red", "OEE was low")}
    assert one.is_struggling
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
    assert set(LegacyRecord.objects.values_list("model", flat=True)) == {"core.meetingcriterion"}
    assert "Not mapped" in output and "core.meetingcriterion" in output and "core.swotitem" not in output.split("Not mapped")[1]


def test_offsites_become_planning_sessions():
    run_import()
    session = Session.objects.get()
    assert session.kind == "annual" and session.team.name == "Kentucky" and session.is_concluded
    items = {(i.section, i.kind, i.text, i.color) for i in session.items.all()}
    assert ("swot", "strength", "Strong team", "") in items
    assert ("segue", "working", "Daily huddles", "") in items
    assert ("segue", "not_working", "Broken: Shift handoff", "") in items
    assert ("review", "lesson", "Start earlier: Plan installs a month ahead", "") in items
    assert ("vto", "vto_check", "Core value · Own It: Visible at every level. (Mostly)", "yellow") in items
    assert ("vto", "vto_check", "Mission · why", "green") in items
    assert any(k == "best_news" and "Chapter title: Momentum (We shipped)" in t for _, k, t, _ in items)
    assert any(k == "priority" and t.startswith("#1: Staffing") for _, k, t, _ in items)
    assert set(session.attendees.values_list("name", flat=True)) == {"Alex Admin", "Drew Plant"}


def test_existing_rows_get_grids_and_updates_without_refresh():
    run_import()
    ConversationScore.objects.all().delete()
    RockUpdate.objects.all().delete()
    run_import()
    assert ConversationScore.objects.count() == 3
    assert RockUpdate.objects.count() == 3


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


def _seat(pk, title, person, parent, status="green"):
    return {"model": "core.seat", "pk": pk, "fields": {
        "facility": 1, "parent": parent, "title": title, "person_name": "", "person": person,
        "status": status, "responsibilities": "", "agency": False, "sort": pk,
    }}


def _person(pk, email, name, role="member"):
    return {"model": "core.user", "pk": pk, "fields": {
        "email": email, "name": name, "role": role, "facility": 1, "is_active": True,
    }}


def _one(pk, user, created_by=None, completed_by=None):
    return {"model": "core.oneonone", "pk": pk, "fields": {
        "user": user, "date": "2026-10-01", "highlight": "", "created_by": created_by, "completed_by": completed_by,
        "completed_at": "2026-10-01T16:00:00Z", "scores": {"cv1": {"rag": "green", "note": ""}},
    }}


# Matt and Jacob each hold a Plant Manager seat under their own Director seat. Joel reports to a
# vacant Quality Director. Yanira reports to a vacant seat. Rachel has no seat. Luke has two chains.
CHART_ROWS = [
    {"model": "core.facility", "pk": 1, "fields": {"name": "Company", "short_code": "CO", "sort": 0}},
    {"model": "core.value", "pk": 1, "fields": {"name": "Own It", "sort": 0, "active": True}},
    _person(1, "ben@steuartnutrition.com", "Ben Steuart", "admin"),
    _person(2, "matt@steuartnutrition.com", "Matt Anderson"),
    _person(3, "jm@steuartnutrition.com", "Jacob Miller"),
    _person(4, "rachel@steuartnutrition.com", "Rachel", "admin"),
    _person(5, "joel@steuartnutrition.com", "Joel Senecal-Moseley"),
    _person(6, "yanira@pending.invalid", "Yanira"),
    _person(7, "leo@steuartnutrition.com", "Leo Hart"),
    _person(8, "luke@steuartnutrition.com", "Luke Mulholland"),
    _seat(1, "Visionary / CEO", 1, None),
    _seat(2, "Integrator", 1, 1, "yellow"),
    _seat(3, "Powder Operations Director", 3, 2),
    _seat(4, "Plant Manager", 3, 3),
    _seat(5, "Liquid Operations Director", 2, 2),
    _seat(6, "Plant Manager", 2, 5),
    _seat(7, "Quality Director", None, 2, "yellow"),
    _seat(8, "QSM KY", 5, 7),
    _seat(10, "Container Line Operator", None, 4, "red"),
    _seat(11, "Senior Production Worker", 6, 10),
    _seat(12, "Le Roy Quality Site Manager", 8, 6),
    _seat(13, "Liquid Quality Site Manager", 8, 7),
    _one(1, 2),                  # Matt, no creator: walk past his own director seat
    _one(2, 2, created_by=2),    # creator is himself, so the chart still decides
    _one(3, 2, created_by=3),    # the old record names Jacob; that wins over the chart
    _one(4, 3),                  # Jacob, stacked the same way
    _one(5, 4),                  # Rachel has no seat: Visionary / CEO
    _one(6, 5, completed_by=7),  # Joel: completed_by before the vacant-parent walk
    _one(7, 6),                  # Yanira: walk past the vacant seat to Jacob
    _one(8, 8),                  # Luke: nearest holder is Matt, not Ben two seats up
    _one(9, 1),                  # Ben: no one above him, and he is not his own manager
]


def _manager_name(legacy_id):
    one = OneOnOne.objects.get(legacy_id=legacy_id)
    assert one.manager_id != one.person_id
    review = PeopleReview.objects.get(notes=f"From 1:1 #{legacy_id} (Battle Planner)")
    assert review.person_id == one.person_id and review.reviewer_id == one.manager_id
    return None if one.manager_id is None else one.manager.name


def test_one_on_one_manager_walks_past_own_and_vacant_seats():
    _import_rows(CHART_ROWS)
    assert _manager_name(1) == "Ben Steuart"
    assert _manager_name(2) == "Ben Steuart"
    assert OneOnOne.objects.get(legacy_id=2).created_by.name == "Matt Anderson"
    assert _manager_name(3) == "Jacob Miller"
    assert _manager_name(4) == "Ben Steuart"
    assert _manager_name(5) == "Ben Steuart"
    assert _manager_name(6) == "Leo Hart"
    assert _manager_name(7) == "Jacob Miller"
    assert _manager_name(8) == "Matt Anderson"
    assert _manager_name(9) is None
    assert not OneOnOne.objects.filter(manager_id=models.F("person_id")).exists()
    assert not PeopleReview.objects.filter(reviewer_id=models.F("person_id")).exists()


def test_reimport_fixes_a_self_or_blank_manager_but_keeps_a_chosen_one():
    _import_rows(CHART_ROWS)
    matt = OneOnOne.objects.get(legacy_id=1)
    matt.manager = matt.person
    matt.save()
    PeopleReview.objects.filter(notes="From 1:1 #1 (Battle Planner)").update(reviewer=None)
    jacob = OneOnOne.objects.get(legacy_id=4)
    leo = User.objects.get(email="leo@steuartnutrition.com")
    jacob.manager = leo
    jacob.save()
    PeopleReview.objects.filter(notes="From 1:1 #4 (Battle Planner)").update(reviewer=leo)

    _import_rows(CHART_ROWS)
    assert _manager_name(1) == "Ben Steuart"
    jacob.refresh_from_db()
    assert jacob.manager == leo
    assert PeopleReview.objects.get(notes="From 1:1 #4 (Battle Planner)").reviewer == leo

    _import_rows(CHART_ROWS, refresh=True)
    assert _manager_name(4) == "Ben Steuart"


def test_sync_removes_nothing_when_the_export_already_matches():
    run_import()
    first = counts()
    output = run_import("--sync")
    assert counts() == first
    assert "Nothing." in output


def test_sync_drops_stale_imports_keeps_native_rows_and_deactivates_users():
    from allauth.socialaccount.models import SocialAccount

    run_import()
    ky = Team.objects.get(name="Kentucky")
    plant = Seat.objects.get(title="Plant Manager")
    rock = Rock.objects.get(title="Close new revenue")
    rock.title = "Edited in the app"
    rock.save()
    alex = User.objects.get(email="alex@steuartnutrition.com")
    alex.set_password("alex-secret")
    alex.save()
    alex_password = alex.password
    SocialAccount.objects.create(user=alex, provider="google", uid="alex-google")
    fran = User.objects.get(email="fran@pending.invalid")

    stale_seat = Seat.objects.create(team=ky, title="Removed seat", legacy_id=999, parent=plant)
    Seat.objects.create(team=ky, title="Native under removed", parent=stale_seat)
    Seat.objects.create(team=ky, title="Native seat")
    Seat.objects.create(team=ky, title="Native under kept", parent=plant)
    gone_rock = Rock.objects.create(quarter=rock.quarter, team=ky, title="Removed in BP", legacy_id=4242)
    Milestone.objects.create(rock=gone_rock, title="Hangs off removed rock")
    Milestone.objects.create(rock=rock, title="Typed in SN EOS")
    Issue.objects.create(team=ky, title="Typed issue")
    Issue.objects.create(team=ky, title="Old box", horizon=Issue.LONG, legacy={"source": "core.box:999"})
    Todo.objects.create(team=ky, owner=alex, title="Typed to-do")
    Todo.objects.create(team=ky, owner=alex, title="Old commitment", legacy_id=8888)
    Team.objects.create(name="Pilot team")
    OneOnOne.objects.create(person=fran, legacy_id=777, date="2026-10-02")
    PeopleReview.objects.create(person=fran, notes="From 1:1 #777 (Battle Planner)")
    PeopleReview.objects.create(person=fran, reviewer=alex, notes="Written in SN EOS")
    left = User.objects.create_user(email="left@steuartnutrition.com", name="Left Person")
    left.legacy_id = 4242
    left.set_password("stay-secret")
    left.save()
    left_password = left.password
    SocialAccount.objects.create(user=left, provider="google", uid="left-google", extra_data={"kept": True})

    output = run_import("--sync")

    rock.refresh_from_db()
    assert rock.title == "Close new revenue"  # --sync implies --refresh
    assert not Seat.objects.filter(title__in=["Removed seat", "Native under removed"]).exists()
    assert Seat.objects.filter(title="Native seat").exists()
    assert Seat.objects.get(title="Native under kept").parent == plant
    assert Seat.objects.filter(title="Plant Manager").exists()
    assert not Rock.objects.filter(legacy_id=4242).exists()
    assert not Milestone.objects.filter(title="Hangs off removed rock").exists()
    assert Milestone.objects.filter(title="Typed in SN EOS").exists()
    assert Issue.objects.filter(title="Typed issue").exists()
    assert not Issue.objects.filter(title="Old box").exists()
    assert Issue.objects.filter(title="Win deals").exists()
    assert Todo.objects.filter(title="Typed to-do").exists()
    assert not Todo.objects.filter(legacy_id=8888).exists()
    assert Team.objects.filter(name="Pilot team").exists()
    assert not OneOnOne.objects.filter(legacy_id=777).exists()
    assert not PeopleReview.objects.filter(notes__startswith="From 1:1 #777").exists()
    assert PeopleReview.objects.filter(notes="Written in SN EOS").exists()
    assert OneOnOne.objects.get(legacy_id=1).manager.name == "Drew Plant"
    left.refresh_from_db()
    assert not left.is_active and left.password == left_password
    assert SocialAccount.objects.filter(user=left, uid="left-google").exists()
    alex.refresh_from_db()
    assert alex.is_active and alex.password == alex_password and alex.has_usable_password()
    assert SocialAccount.objects.filter(user=alex, uid="alex-google").exists()
    assert "Removed (no longer in the export):" in output
    assert "Users deactivated" in output
    assert "Nothing." not in output

    again = run_import("--sync")
    assert "Nothing." in again
    left.refresh_from_db()
    assert not left.is_active and left.password == left_password


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
