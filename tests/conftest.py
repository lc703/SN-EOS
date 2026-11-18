import datetime as dt

import pytest
from django.test import Client

from core.models import Quarter, Team, User


@pytest.fixture
def quarter(db):
    return Quarter.objects.create(name="Q4 2026", start_date=dt.date(2026, 10, 1), end_date=dt.date(2026, 12, 31), is_current=True)


@pytest.fixture
def teams(db):
    return {
        "company": Team.objects.create(name="Company", short_code="CO", is_leadership=True, sort=0),
        "ky": Team.objects.create(name="Kentucky", short_code="KY", sort=1),
        "lr": Team.objects.create(name="Le Roy", short_code="LR", sort=2),
    }


def make_user(email, name, role=User.ROLE_MEMBER, teams=()):
    user = User.objects.create_user(email=email, name=name, role=role)
    for t in teams:
        t.members.add(user)
    return user


@pytest.fixture
def admin(teams):
    return make_user("admin@steuartnutrition.com", "Ada Admin", User.ROLE_ADMIN, [teams["company"]])


@pytest.fixture
def member(teams):
    return make_user("kim@steuartnutrition.com", "Kim Member", teams=[teams["ky"]])


@pytest.fixture
def other(teams):
    return make_user("lee@steuartnutrition.com", "Lee Other", teams=[teams["lr"]])


@pytest.fixture
def ky_peer(teams):
    return make_user("pat@steuartnutrition.com", "Pat Peer", teams=[teams["ky"]])


def client_for(user, team=None):
    c = Client()
    c.force_login(user)
    if team is not None:
        session = c.session
        session["team_id"] = team.pk
        session.save()
    return c


@pytest.fixture
def as_user():
    return client_for
