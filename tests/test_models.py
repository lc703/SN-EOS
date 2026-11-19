import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import Quarter, User
from issues.models import Issue
from scorecard.models import Measurable
from todos.models import Todo, completion, weekly_completion


def test_quarter_has_13_monday_weeks_starting_with_the_first_week(quarter):
    weeks = quarter.weeks()
    assert len(weeks) == 13
    assert all(w.weekday() == 0 for w in weeks)
    assert weeks[0] <= quarter.start_date < weeks[0] + dt.timedelta(days=7)
    assert weeks[1] - weeks[0] == dt.timedelta(days=7)


@pytest.mark.django_db
def test_quarter_for_calendar_creates_calendar_quarters():
    q = Quarter.for_calendar(dt.date(2027, 2, 14))
    assert (q.name, q.start_date, q.end_date) == ("Q1 2027", dt.date(2027, 1, 1), dt.date(2027, 3, 31))
    q4 = Quarter.for_calendar(dt.date(2026, 11, 1))
    assert q4.end_date == dt.date(2026, 12, 31)
    assert Quarter.for_calendar(dt.date(2027, 3, 1)).pk == q.pk


@pytest.mark.parametrize(
    "compare,goal,value,expected",
    [
        ("gte", 10, 10, True),
        ("gte", 10, 9.5, False),
        ("lte", 3, 2, True),
        ("lte", 3, 4, False),
        ("eq", 1, 1, True),
        ("eq", 1, 0, False),
    ],
)
def test_measurable_goal_comparison(compare, goal, value, expected):
    m = Measurable(goal_compare=compare, goal=Decimal(goal))
    assert m.is_on_goal(Decimal(str(value))) is expected


def test_measurable_without_goal_or_value_is_neutral():
    assert Measurable(goal=None).is_on_goal(Decimal(5)) is None
    assert Measurable(goal=Decimal(5)).is_on_goal(None) is None


def test_measurable_formatting_and_parsing():
    pct = Measurable(unit=Measurable.UNIT_PERCENT, goal_compare="gte", goal=Decimal("85"))
    assert pct.format_value(Decimal("72.50")) == "72.5%"
    assert pct.goal_display == "≥ 85%"
    assert Measurable(unit=Measurable.UNIT_CURRENCY).format_value(Decimal("12500")) == "$12,500"
    yn = Measurable(unit=Measurable.UNIT_YESNO, goal=Decimal(1))
    assert yn.format_value(Decimal(1)) == "Yes" and yn.goal_display == "Yes"
    assert Measurable.parse("$1,200", Measurable.UNIT_CURRENCY) == Decimal("1200")
    assert Measurable.parse("85%", Measurable.UNIT_PERCENT) == Decimal("85")
    assert Measurable.parse("no", Measurable.UNIT_YESNO) == Decimal(0)
    assert Measurable.parse("", Measurable.UNIT_NUMBER) is None
    with pytest.raises(ValueError):
        Measurable.parse("abc", Measurable.UNIT_NUMBER)


def test_measurable_trailing_average_and_total():
    vals = [Decimal(1), Decimal(2), None, Decimal(6)]
    assert Measurable(trailing="avg").trailing_value(vals) == Decimal("3.00")
    assert Measurable(trailing="total").trailing_value(vals) == Decimal(9)
    assert Measurable(trailing="").trailing_value(vals) is None


@pytest.mark.django_db
def test_todo_defaults_to_seven_days_and_allows_past_dates(member, teams):
    t = Todo.objects.create(team=teams["ky"], title="Call vendor", owner=member)
    assert t.due_date == timezone.localdate() + dt.timedelta(days=7)
    past = Todo.objects.create(team=teams["ky"], title="Late", owner=member, due_date=dt.date(2020, 1, 1))
    assert past.overdue
    past.set_done(True)
    assert past.done and past.done_at and not past.overdue


@pytest.mark.django_db
def test_completion_percentages(member, teams):
    today = dt.date(2026, 11, 18)  # a Wednesday
    monday = dt.date(2026, 11, 16)
    for i, done in enumerate([True, True, False, True]):
        Todo.objects.create(team=teams["ky"], title=f"t{i}", owner=member, due_date=monday + dt.timedelta(days=i), done=done)
    assert completion(Todo.objects.all()) == 75
    assert completion([]) is None
    rows = weekly_completion(Todo.objects.all(), weeks=2, today=today)
    assert rows[-1] == (monday, 75, 3, 4)
    assert rows[0][1] is None


@pytest.mark.django_db
def test_issue_priority_is_unique_per_team_list(member, teams):
    a = Issue.objects.create(team=teams["ky"], title="A", owner=member)
    b = Issue.objects.create(team=teams["ky"], title="B", owner=member)
    elsewhere = Issue.objects.create(team=teams["lr"], title="C", owner=member, priority=1)
    a.set_priority(1)
    b.set_priority(1)
    a.refresh_from_db(), elsewhere.refresh_from_db()
    assert (a.priority, b.priority, elsewhere.priority) == (None, 1, 1)


@pytest.mark.django_db
def test_issue_solve_and_reopen(member, teams):
    i = Issue.objects.create(team=teams["ky"], title="A", owner=member, priority=2)
    i.solve(resolution="Decided")
    assert i.status == Issue.SOLVED and i.solved_at and i.priority is None and i.resolution == "Decided"
    i.reopen()
    assert i.is_open and i.solved_at is None


@pytest.mark.django_db
def test_user_roles_and_names():
    u = User.objects.create_user(email="Jo.Smith@SteuartNutrition.com", name="Jo Smith-Jones")
    assert u.email == "jo.smith@steuartnutrition.com" and u.username == u.email
    assert u.initials == "JS" and u.first == "Jo"
    assert not u.is_admin and u.can_sign_in
    u.role = User.ROLE_ADMIN
    u.save()
    assert u.is_admin and u.is_staff
    assert not User(email="x@pending.invalid").can_sign_in
