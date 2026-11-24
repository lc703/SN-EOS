import pytest
from django.test import Client, override_settings

from core.adapters import email_allowed
from issues.models import Issue
from people.models import OneOnOne
from rocks.models import Rock
from todos.models import Todo
from vision.models import VTO, Seat

pytestmark = pytest.mark.django_db


def test_login_required_and_public_endpoints(member):
    c = Client()
    r = c.get("/rocks/")
    assert r.status_code == 302 and r.url.startswith("/accounts/login/")
    assert c.get("/healthz").status_code == 200
    assert c.get("/accounts/login/").status_code == 200


def test_dev_login_only_when_enabled(member):
    c = Client()
    assert c.post("/dev-login/", {"user": member.pk}).status_code == 302
    assert c.get("/").status_code == 200
    with override_settings(DEV_LOGIN=False):
        assert Client().get("/dev-login/").status_code == 404


def test_email_domain_restriction():
    assert email_allowed("ben@steuartnutrition.com")
    assert email_allowed("BEN@SteuartNutrition.com")
    assert not email_allowed("ben@gmail.com")
    assert not email_allowed("ben@steuartnutrition.com.evil.io")
    assert not email_allowed("")


def test_member_edits_own_rock_but_not_others(as_user, teams, member, ky_peer, admin, quarter):
    mine = Rock.objects.create(quarter=quarter, team=teams["ky"], title="Mine", owner=member)
    theirs = Rock.objects.create(quarter=quarter, team=teams["ky"], title="Theirs", owner=ky_peer)
    c = as_user(member)
    assert c.post(f"/rocks/{mine.pk}/status/", {"status": "off_track"}).status_code == 302
    assert c.post(f"/rocks/{theirs.pk}/status/", {"status": "off_track"}).status_code == 403
    assert c.post(f"/rocks/{theirs.pk}/milestones/", {"title": "x"}).status_code == 403
    assert as_user(admin).post(f"/rocks/{theirs.pk}/status/", {"status": "done"}).status_code == 302
    mine.refresh_from_db(), theirs.refresh_from_db()
    assert (mine.status, theirs.status) == (Rock.OFF_TRACK, Rock.DONE)


def test_members_edit_their_teams_issues_and_todos_only(as_user, teams, member, ky_peer, other):
    issue = Issue.objects.create(team=teams["ky"], title="Team issue", owner=ky_peer)
    todo = Todo.objects.create(team=teams["ky"], title="Team todo", owner=ky_peer)
    assert as_user(member).post(f"/issues/{issue.pk}/priority/", {"rank": "1"}).status_code == 302
    assert as_user(member).post(f"/todos/{todo.pk}/toggle/", {"done": "1"}).status_code == 302
    assert as_user(other).post(f"/issues/{issue.pk}/solve/", {"action": "solve"}).status_code == 403
    assert as_user(other).post(f"/todos/{todo.pk}/toggle/", {"done": ""}).status_code == 403
    assert as_user(other, teams["ky"]).post("/issues/new/", {"title": "Sneaky", "horizon": "short"}).status_code == 403
    issue.refresh_from_db(), todo.refresh_from_db()
    assert issue.priority == 1 and todo.done and issue.is_open


def test_private_todos_are_private(as_user, teams, member, ky_peer):
    as_user(member, teams["ky"]).post("/todos/new/", {"title": "Secret thing", "owner": member.pk, "is_private": "1", "due_date": "2026-12-01"})
    todo = Todo.objects.get()
    assert todo.is_private
    assert "Secret thing" in as_user(member, teams["ky"]).get("/todos/").content.decode()
    assert "Secret thing" not in as_user(ky_peer, teams["ky"]).get("/todos/").content.decode()
    assert as_user(ky_peer).get(f"/todos/{todo.pk}/").status_code == 403


def test_vto_and_chart_are_admin_only(as_user, admin, member, teams):
    assert as_user(member).get("/vto/").status_code == 200
    assert as_user(member).get("/vto/edit/").status_code == 403
    assert as_user(member).post("/chart/seats/new/", {"title": "Boss"}).status_code == 403
    r = as_user(admin, teams["ky"]).post("/chart/seats/new/", {"title": "Plant Manager", "team": teams["ky"].pk, "roles": "a\nb", "sort": 0})
    assert r.status_code == 302 and Seat.objects.get().title == "Plant Manager"
    data = {f: "" for f in ["purpose", "niche", "ten_year_target"]} | {"purpose": "Glorify God", "cv-TOTAL_FORMS": "0", "cv-INITIAL_FORMS": "0"}
    assert as_user(admin).post("/vto/edit/", data).status_code == 302
    assert VTO.load().purpose == "Glorify God"


def test_one_on_ones_visible_to_person_manager_and_admins(as_user, teams, admin, member, ky_peer, other):
    boss_seat = Seat.objects.create(team=teams["ky"], title="Plant Manager", person=ky_peer)
    Seat.objects.create(team=teams["ky"], title="Line Lead", person=member, parent=boss_seat)
    OneOnOne.objects.create(person=member, manager=ky_peer, notes="Confidential coaching note")
    url = f"/people/{member.pk}/"
    for viewer in (member, ky_peer, admin):
        assert "Confidential coaching note" in as_user(viewer).get(url).content.decode()
    assert "Confidential coaching note" not in as_user(other).get(url).content.decode()
    assert as_user(other).post(f"/people/{member.pk}/one-on-ones/", {"notes": "x"}).status_code == 403
    assert as_user(member).post(f"/people/{member.pk}/reviews/", {}).status_code == 403  # can't review yourself
    assert as_user(ky_peer).post(f"/people/{member.pk}/reviews/", {"gets_it": "yes"}).status_code == 302


def test_export_is_admin_only_and_has_no_passwords(as_user, admin, member):
    assert as_user(member).get("/export.json").status_code == 403
    r = as_user(admin).get("/export.json")
    assert r.status_code == 200 and "attachment" in r["Content-Disposition"]
    rows = r.json()
    users = [row for row in rows if row["model"] == "core.user"]
    assert users and all("password" not in row["fields"] for row in users)


def _password_user(email="pw@steuartnutrition.com"):
    from core.models import User

    user = User.objects.create_user(email=email, name="Pw User")
    user.set_password("s3cret-pass")
    user.save()
    return user


@override_settings(STAGING_PASSWORD_LOGIN=False)
def test_password_login_off_by_default(monkeypatch):
    from django.conf import settings

    # The staging box exports STAGING_PASSWORD_LOGIN=1. The test has to force it off
    # instead of asserting whatever the process environment loaded.
    monkeypatch.setenv("STAGING_PASSWORD_LOGIN", "0")
    assert settings.STAGING_PASSWORD_LOGIN is False
    _password_user()
    c = Client()
    r = c.post("/accounts/password-login/", {"email": "pw@steuartnutrition.com", "password": "s3cret-pass"})
    assert r.status_code == 404
    assert c.get("/rocks/").status_code == 302
    assert b"Or sign in with a password" not in c.get("/accounts/login/").content


@override_settings(STAGING_PASSWORD_LOGIN=True)
def test_password_login_when_enabled():
    _password_user()
    c = Client()
    assert b"Or sign in with a password" in c.get("/accounts/login/").content
    r = c.post("/accounts/password-login/", {"email": "PW@steuartnutrition.com", "password": "s3cret-pass", "next": "/rocks/"})
    assert r.status_code == 302 and r.url == "/rocks/"
    assert c.get("/rocks/").status_code == 200


@override_settings(STAGING_PASSWORD_LOGIN=True)
def test_password_login_rejects_bad_password_other_domain_and_open_redirect():
    _password_user()
    _password_user("pw@gmail.com")
    c = Client()
    assert c.post("/accounts/password-login/", {"email": "pw@steuartnutrition.com", "password": "nope"}).status_code == 400
    assert c.post("/accounts/password-login/", {"email": "pw@gmail.com", "password": "s3cret-pass"}).status_code == 400
    assert c.get("/rocks/").status_code == 302
    r = c.post("/accounts/password-login/", {"email": "pw@steuartnutrition.com", "password": "s3cret-pass", "next": "https://evil.example/"})
    assert r.status_code == 302 and r.url == "/"
    assert c.get("/accounts/password-login/").status_code == 405


@override_settings(STAGING_PASSWORD_LOGIN=True)
def test_password_login_never_signs_up():
    from core.models import User

    c = Client()
    r = c.post("/accounts/password-login/", {"email": "new@steuartnutrition.com", "password": "whatever"})
    assert r.status_code == 400
    assert not User.objects.filter(email="new@steuartnutrition.com").exists()
