"""An admin who is not on a site can add issues, to-dos and rocks there (and in its L10), owned by themselves,
and a refused add shows why. Regression: the owner select offered the signed-in user but the form's queryset
did not, so the post failed validation and the redirect hid the reason."""

import re
from html import unescape

import pytest
from django.utils import timezone

from core.forms import owner_choices
from core.models import User
from issues.models import Issue
from meetings.models import Meeting
from rocks.models import Rock
from todos.models import Todo
from tests.conftest import client_for
from tests.test_rollup import all_teams, cur_q, get, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


def submit_form(body, action):
    """What a browser would post for the form with this action: inputs, textareas, and each select's chosen
    option (the selected one, else the first, exactly as a browser does)."""
    form = re.search(rf'<form[^>]*action="{re.escape(action)}"[^>]*>(.*?)</form>', body, re.S).group(1)
    data = {}
    for tag in re.findall(r"<input[^>]*>", form):
        name = re.search(r'name="([^"]+)"', tag)
        if not name or re.search(r'type="(checkbox|radio)"', tag) and "checked" not in tag:
            continue
        value = re.search(r'value="([^"]*)"', tag)
        data[name.group(1)] = unescape(value.group(1)) if value else "on"
    for name, inner in re.findall(r'<textarea[^>]*name="([^"]+)"[^>]*>(.*?)</textarea>', form, re.S):
        data[name] = unescape(inner).strip()
    for name, inner in re.findall(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', form, re.S):
        options = re.findall(r'<option value="([^"]*)"([^>]*)>', inner)
        chosen = next((v for v, attrs in options if "selected" in attrs), options[0][0] if options else "")
        data[name] = chosen
    return data


@pytest.fixture
def lucas(admin, all_teams):
    """Superuser, on the Company team only."""
    assert not admin.teams.filter(pk=all_teams["ky"].pk).exists()
    return admin


def test_owner_choices_always_offer_the_user_and_the_current_owner(lucas, member, all_teams):
    ky = all_teams["ky"]
    assert lucas in owner_choices(ky, user=lucas)
    assert lucas not in owner_choices(ky)  # the mismatch the bug came from
    inactive = User.objects.create_user(email="gone@steuartnutrition.com", name="Gone", is_active=False)
    issue = Issue.objects.create(team=ky, title="x", owner=inactive)
    for team in (ky, all_teams["company"], None):
        assert inactive in owner_choices(team, user=member, instance=issue)
        assert inactive not in owner_choices(team, user=member)


# ---- issues -------------------------------------------------------------------------------------------

def test_admin_off_the_site_adds_an_issue_from_the_site_issues_bar(lucas, all_teams, world):
    c = client_for(lucas, all_teams["ky"])
    body = c.get("/issues/").content.decode()
    data = submit_form(body, "/issues/new/")
    assert data["owner"] == str(lucas.pk) and data["team"] == str(all_teams["ky"].pk)
    r = c.post("/issues/new/", {**data, "title": "Lucas raises it on KY"})
    issue = Issue.objects.get(title="Lucas raises it on KY")
    assert (issue.team, issue.owner, issue.horizon) == (all_teams["ky"], lucas, "short")
    assert r.status_code == 302 and "Lucas raises it on KY" in c.get(r["Location"]).content.decode()


def test_admin_off_the_site_adds_an_issue_in_the_site_l10(lucas, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate(), facilitator=lucas)
    c = client_for(lucas, all_teams["company"])
    data = submit_form(c.get(f"/meetings/{meeting.pk}/?s=ids").content.decode(), "/issues/new/")
    assert data["owner"] == str(lucas.pk)
    r = c.post("/issues/new/", {**data, "title": "Raised in the KY L10"})
    issue = Issue.objects.get(title="Raised in the KY L10")
    assert (issue.team, issue.owner, issue.raised_meeting) == (all_teams["ky"], lucas, meeting)
    assert "Raised in the KY L10" in c.get(r["Location"]).content.decode()


def test_editing_an_issue_as_an_admin_off_the_site_keeps_the_owner(lucas, all_teams, world):
    issue = Issue.objects.create(team=all_teams["ky"], title="Lucas's issue", owner=lucas)
    c = client_for(lucas, all_teams["ky"])
    data = submit_form(c.get(f"/issues/{issue.pk}/").content.decode(), f"/issues/{issue.pk}/")
    data["title"] = "Renamed"
    assert c.post(f"/issues/{issue.pk}/", data).status_code == 302
    issue.refresh_from_db()
    assert (issue.title, issue.owner) == ("Renamed", lucas)


# ---- to-dos -------------------------------------------------------------------------------------------

def test_admin_off_the_site_adds_a_todo_on_the_site_page(lucas, all_teams, world):
    c = client_for(lucas, all_teams["ky"])
    data = submit_form(c.get("/todos/").content.decode(), "/todos/new/")
    assert data["owner"] == str(lucas.pk)
    c.post("/todos/new/", {**data, "title": "Lucas to-do on KY"})
    todo = Todo.objects.get(title="Lucas to-do on KY")
    assert (todo.team, todo.owner) == (all_teams["ky"], lucas)


def test_admin_off_the_site_adds_a_todo_in_the_site_l10_filed_on_the_meetings_team(lucas, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate(), facilitator=lucas)
    c = client_for(lucas, all_teams["company"])  # the session is on Company, the meeting is Kentucky's
    data = submit_form(c.get(f"/meetings/{meeting.pk}/?s=todos").content.decode(), "/todos/new/")
    assert data["meeting"] == str(meeting.pk) and data["owner"] == str(lucas.pk)
    r = c.post("/todos/new/", {**data, "title": "From the KY L10"})
    todo = Todo.objects.get(title="From the KY L10")
    assert (todo.team, todo.owner, todo.meeting) == (all_teams["ky"], lucas, meeting)
    assert r["Location"] == f"/meetings/{meeting.pk}/?s=todos"


def test_a_site_member_off_the_meeting_still_cannot_add_to_its_l10(other, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate())
    r = client_for(other, all_teams["lr"]).post("/todos/new/", {"title": "Nope", "owner": other.pk, "meeting": meeting.pk})
    assert r.status_code == 403 and not Todo.objects.filter(title="Nope").exists()


# ---- rocks --------------------------------------------------------------------------------------------

def test_admin_off_the_site_adds_a_rock_on_the_site_page(lucas, all_teams, world, cur_q):
    c = client_for(lucas, all_teams["ky"])
    data = submit_form(c.get("/rocks/").content.decode(), "/rocks/new/")
    assert data["owner"] == str(lucas.pk)
    r = c.post("/rocks/new/", {**data, "title": "Lucas rock on KY", "due_date": cur_q.end_date.isoformat()})
    rock = Rock.objects.get(title="Lucas rock on KY")
    assert (rock.team, rock.owner) == (all_teams["ky"], lucas) and r.status_code == 302


def test_every_owner_select_offers_the_signed_in_admin(lucas, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate(), facilitator=lucas)
    c = client_for(lucas, all_teams["ky"])
    for path in ("/issues/", "/todos/", "/rocks/", f"/meetings/{meeting.pk}/?s=ids", f"/meetings/{meeting.pk}/?s=todos"):
        body = c.get(path).content.decode()
        assert re.search(rf'<option value="{lucas.pk}"\s+selected', body), path


# ---- refused adds say why -----------------------------------------------------------------------------

def test_a_refused_issue_shows_the_reasons_and_keeps_what_was_typed(lucas, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate(), facilitator=lucas)
    c = client_for(lucas, all_teams["ky"])
    data = submit_form(c.get(f"/meetings/{meeting.pk}/?s=ids").content.decode(), "/issues/new/")
    r = c.post("/issues/new/", {**data, "title": "Typed but refused", "owner": "999999"})
    assert not Issue.objects.filter(title="Typed but refused").exists()
    page = c.get(r["Location"]).content.decode()
    assert "Couldn&#x27;t add that issue" in page or "Couldn't add that issue" in page
    assert "Owner:" in page and "Select a valid choice" in page
    assert 'value="Typed but refused"' in page
    assert "Select a valid choice" not in c.get(r["Location"]).content.decode()  # shown once


def test_a_blank_title_is_explained_on_the_site_issues_list(lucas, all_teams, world):
    c = client_for(lucas, all_teams["ky"])
    data = submit_form(c.get("/issues/").content.decode(), "/issues/new/")
    r = c.post("/issues/new/", {**data, "title": "   "})
    page = c.get(r["Location"]).content.decode()
    assert 'role="alert"' in page and "Title:" in page


def test_a_refused_todo_shows_the_reasons_in_the_l10_and_on_the_list(lucas, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate(), facilitator=lucas)
    c = client_for(lucas, all_teams["ky"])
    for path, back in ((f"/meetings/{meeting.pk}/?s=todos", f"/meetings/{meeting.pk}/?s=todos"), ("/todos/", "/todos/")):
        data = submit_form(c.get(path).content.decode(), "/todos/new/")
        r = c.post("/todos/new/", {**data, "title": "Refused to-do", "owner": "999999"})
        assert r["Location"] == back
        page = c.get(back).content.decode()
        assert "Couldn&#x27;t add that to-do" in page or "Couldn't add that to-do" in page
        assert "Owner:" in page and 'value="Refused to-do"' in page
    assert not Todo.objects.filter(title="Refused to-do").exists()


def test_a_refused_rock_reopens_the_form_with_the_reasons(lucas, all_teams, world, cur_q):
    c = client_for(lucas, all_teams["ky"])
    data = submit_form(c.get("/rocks/").content.decode(), "/rocks/new/")
    r = c.post("/rocks/new/", {**data, "title": ""})
    page = c.get(r["Location"]).content.decode()
    assert "Title:" in page and "Couldn&#x27;t add that rock" in page or "Couldn't add that rock" in page
    assert "open: true" in page
    assert "open: true" not in c.get("/rocks/").content.decode()


def test_the_old_flash_only_failure_is_gone(lucas, all_teams, world):
    c = client_for(lucas, all_teams["ky"])
    c.post("/issues/new/", {"title": "x", "horizon": "short", "team": all_teams["ky"].pk, "owner": "999999"})
    assert list(c.get("/issues/").context["messages"]) == []
