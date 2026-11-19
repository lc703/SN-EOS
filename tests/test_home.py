import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import monday_of
from rocks.models import Rock, RockUpdate
from scorecard.models import Measurable, ScoreEntry
from todos.models import Todo

pytestmark = pytest.mark.django_db


def test_dashboard_flags_what_needs_attention(as_user, teams, member, quarter):
    today = timezone.localdate()
    Rock.objects.create(team=teams["ky"], quarter=quarter, title="New die", owner=member)
    Measurable.objects.create(team=teams["ky"], title="OEE", owner=member, goal=Decimal(65))
    Todo.objects.create(team=teams["ky"], title="Call vendor", owner=member, due_date=today - dt.timedelta(days=2))
    html = as_user(member, teams["ky"]).get("/").content.decode()
    assert "3 things need you this week" in html
    assert "1 rock update due" in html
    assert "1 number missing for last week" in html and "OEE" in html
    assert "1 overdue to-do" in html


def test_dashboard_caught_up_and_charts(as_user, teams, member, quarter):
    rock = Rock.objects.create(team=teams["ky"], quarter=quarter, title="New die", owner=member)
    RockUpdate.objects.create(rock=rock, week_start=monday_of(timezone.localdate()), rag="green")
    m = Measurable.objects.create(team=teams["ky"], title="OEE", owner=member, goal=Decimal(65))
    for w in quarter.weeks():
        if w < monday_of(timezone.localdate()):
            ScoreEntry.objects.create(measurable=m, week_start=w, value=Decimal(70))
    html = as_user(member, teams["ky"]).get("/").content.decode()
    assert "caught up" in html
    assert "Scorecard on goal" in html and "100%" in html
    assert "Kentucky rocks" in html and "<svg" in html
