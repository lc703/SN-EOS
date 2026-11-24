"""Opening a rock, issue, to-do or measurable from an L10 section and coming back lands on that same section."""

import re
from urllib.parse import quote, unquote

import pytest

from meetings.models import SECTION_KEYS
from tests.conftest import client_for
from tests.test_l10_attendees import l10, page
from tests.test_rollup import all_teams, cur_q, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


def froms(body):
    return {unquote(m) for m in re.findall(r"(?:\?|&amp;|&)from=([^\"'&\s]+)", body)}


def back_link(body):
    m = re.search(r'<a href="([^"]+)" class="l10-back[^"]*"[^>]*>← ([^<]+)</a>', body)
    return m.groups() if m else None


@pytest.fixture
def meeting(member, all_teams, world, cur_q):
    return l10(all_teams["ky"], cur_q, member, facilitator=member)


def test_rock_links_in_the_rock_review_return_to_that_section(member, meeting, world):
    body = page(member, meeting, "rocks")
    assert froms(body) == {f"/meetings/{meeting.pk}/?s=rocks"}
    assert f'/rocks/{world["rocks"]["ky"].pk}/?from=' in body


def test_issue_links_in_ids_return_to_that_section_and_keep_the_meeting(member, meeting, world):
    body = page(member, meeting, "ids")
    pk = world["issues"]["ky"].pk
    assert f'/issues/{pk}/?meeting={meeting.pk}&amp;from=' in body
    assert froms(body) == {f"/meetings/{meeting.pk}/?s=ids"}


def test_todo_links_in_the_todo_list_return_to_that_section(member, meeting, world):
    body = page(member, meeting, "todos")
    assert f'/todos/{world["todos"]["ky"].pk}/?from=' in body
    assert froms(body) == {f"/meetings/{meeting.pk}/?s=todos"}


def test_scorecard_edit_link_returns_to_the_scorecard_section(member, meeting, world):
    body = page(member, meeting, "scorecard")
    assert f'/scorecard/{world["oee"]["kentucky"].pk}/edit/?from=' in body
    assert froms(body) == {f"/meetings/{meeting.pk}/?s=scorecard"}
    panel = client_for(member).get(f"/scorecard/{world['oee']['kentucky'].pk}/panel/?meeting={meeting.pk}").content.decode()
    assert froms(panel) == {f"/meetings/{meeting.pk}/?s=scorecard"}


def test_todos_on_the_conclude_recap_return_to_conclude(member, meeting, world):
    from todos.models import Todo

    Todo.objects.filter(pk=world["todos"]["ky"].pk).update(meeting=meeting)
    body = page(member, meeting, "conclude")
    assert f"/meetings/{meeting.pk}/?s=conclude" in froms(body)
    assert froms(body) == {f"/meetings/{meeting.pk}/?s=conclude"}


def test_show_all_is_kept_in_the_return_link(member, admin, meeting, world):
    body = page(member, meeting, "rocks", "&all=1")
    assert froms(body) == {f"/meetings/{meeting.pk}/?s=rocks&all=1"}


def test_rows_outside_an_l10_carry_no_return_param(member, all_teams, world):
    for path in ("/rocks/", "/todos/", "/issues/", "/scorecard/"):
        assert "from=" not in client_for(member, all_teams["ky"]).get(path).content.decode(), path


def test_todo_toggle_in_an_l10_keeps_the_return_link(member, meeting, world):
    r = client_for(member).post(
        f"/todos/{world['todos']['ky'].pk}/toggle/",
        {"partial": "1", "done": "1", "meeting": meeting.pk, "section": "todos"},
        HTTP_HX_REQUEST="true",
    )
    assert froms(r.content.decode()) == {f"/meetings/{meeting.pk}/?s=todos"}


@pytest.mark.parametrize(
    "path,name,key",
    [
        ("/rocks/{rock}/", "Rock", "rocks"),
        ("/issues/{issue}/", "Issue", "ids"),
        ("/todos/{todo}/", "Todo", "todos"),
        ("/scorecard/{m}/edit/", "Measurable", "scorecard"),
    ],
)
def test_detail_pages_show_a_back_to_l10_link(member, meeting, world, path, name, key):
    url = path.format(rock=world["rocks"]["ky"].pk, issue=world["issues"]["ky"].pk, todo=world["todos"]["ky"].pk, m=world["oee"]["kentucky"].pk)
    label = dict(__import__("meetings.models", fromlist=["SECTIONS"]).SECTIONS)[key]
    target = f"/meetings/{meeting.pk}/?s={key}"
    body = client_for(member).get(f"{url}?from={quote(target, safe='')}").content.decode()
    assert back_link(body) == (target, f"Back to L10 – {label}")
    assert "l10-back" not in client_for(member).get(url).content.decode()


def test_back_link_keeps_show_all(member, meeting, world):
    target = f"/meetings/{meeting.pk}/?s=rocks&all=1"
    body = client_for(member).get(f"/rocks/{world['rocks']['ky'].pk}/?from={quote(target, safe='')}").content.decode()
    assert back_link(body)[0] == target.replace("&", "&amp;") or back_link(body)[0] == target


def test_the_return_param_survives_the_chain_of_detail_pages(member, meeting, world):
    target = f"/meetings/{meeting.pk}/?s=todos"
    qs = quote(target, safe="")
    body = client_for(member).get(f"/rocks/{world['rocks']['ky'].pk}/?from={qs}").content.decode()
    assert f"from={qs}" in body  # the form posts back with it, so a save does not lose the way back
    todo = client_for(member).get(f"/todos/{world['todos']['ky'].pk}/?from={qs}").content.decode()
    assert f'name="next" value="{target}"' in todo


# ---- the return value is validated ---------------------------------------------------------------------

UNSAFE = [
    "//evil.example/meetings/1/?s=rocks",
    "https://evil.example/meetings/1/?s=rocks",
    "http://testserver/meetings/1/?s=rocks",
    "/\\evil.example/",
    "\\\\evil.example",
    "javascript:alert(1)",
    "/rocks/",
    "/meetings/",
    "/meetings/abc/?s=rocks",
    "/meetings/{id}/other/?s=rocks",
    "/meetings/{id}/?s=nope",
    "/meetings/{id}/",
    "/meetings/{id}/?s=rocks#x",
    "/meetings/{id}/?s=rocks\r\nSet-Cookie: a=b",
    "/meetings/99999999/?s=rocks",
    "meetings/{id}/?s=rocks",
    "/meetings/{id}/?s=" + "r" * 300,
    "",
]


@pytest.mark.parametrize("raw", UNSAFE)
def test_unsafe_or_unknown_return_values_are_ignored(member, meeting, world, raw):
    raw = raw.replace("{id}", str(meeting.pk))
    c = client_for(member)
    body = c.get(f"/rocks/{world['rocks']['ky'].pk}/", {"from": raw}).content.decode()
    assert "l10-back" not in body and 'href="//evil' not in body and 'href="https://evil' not in body


@pytest.mark.parametrize("raw", UNSAFE[:-1])
def test_unsafe_return_values_never_become_a_redirect(member, meeting, world, raw):
    raw = raw.replace("{id}", str(meeting.pk))
    c = client_for(member)
    r = c.post(f"/rocks/{world['rocks']['ky'].pk}/?from=" + quote(raw, safe=""), {"delete": "1"})
    assert r.status_code == 302 and r["Location"] == "/rocks/"
    todo = world["todos"]["ky"]
    r = c.post(f"/todos/{todo.pk}/?from=" + quote(raw, safe=""), {"delete": "1"})
    assert r.status_code == 302 and "evil" not in r["Location"] and r["Location"].startswith("/") and not r["Location"].startswith("//")


def test_a_valid_return_is_rebuilt_not_echoed(member, meeting, world):
    raw = f"/meetings/{meeting.pk}/?s=rocks&all=1&evil=1&team=x"
    body = client_for(member).get(f"/rocks/{world['rocks']['ky'].pk}/", {"from": raw}).content.decode()
    assert back_link(body)[0].replace("&amp;", "&") == f"/meetings/{meeting.pk}/?s=rocks&all=1"


def test_actions_on_a_detail_page_go_back_to_the_l10_section(member, meeting, world):
    qs = quote(f"/meetings/{meeting.pk}/?s=rocks", safe="")
    c = client_for(member)
    rock = world["rocks"]["ky"]
    saved = c.post(f"/rocks/{rock.pk}/?from={qs}", {"title": "Renamed", "owner": member.pk, "kind": "departmental", "status": "on_track", "quarter": rock.quarter_id, "team": rock.team_id})
    assert saved.status_code == 302 and saved["Location"] == f"/rocks/{rock.pk}/?from={qs}"
    deleted = c.post(f"/rocks/{rock.pk}/?from={qs}", {"delete": "1"})
    assert deleted["Location"] == f"/meetings/{meeting.pk}/?s=rocks"
    issue = world["issues"]["ky"]
    r = c.post(f"/issues/{issue.pk}/?from={qs}", {"delete": "1"})
    assert r["Location"] == f"/meetings/{meeting.pk}/?s=rocks"
    m = world["oee"]["kentucky"]
    r = c.post(f"/scorecard/{m.pk}/edit/?from={qs}", {"archive": "1"})
    assert r["Location"] == f"/meetings/{meeting.pk}/?s=rocks"
    todo = world["todos"]["ky"]
    r = c.post(f"/todos/{todo.pk}/?from={qs}", {"delete": "1", "next": f"/meetings/{meeting.pk}/?s=rocks"})
    assert r["Location"] == f"/meetings/{meeting.pk}/?s=rocks"


# ---- the meeting page keeps the section in its URL -------------------------------------------------------

@pytest.mark.parametrize("section", SECTION_KEYS)
def test_every_section_pins_itself_into_the_url(member, meeting, section):
    body = page(member, meeting, section)
    assert f'searchParams.set("s", "{section}")' in body and "history.replaceState" in body


def test_the_bare_meeting_url_pins_the_current_section(member, meeting):
    meeting.current_section = "rocks"
    meeting.save()
    body = client_for(member).get(f"/meetings/{meeting.pk}/").content.decode()
    assert 'searchParams.set("s", "rocks")' in body


def test_section_navigation_keeps_show_all(member, meeting):
    body = page(member, meeting, "rocks", "&all=1")
    assert 'href="?s=segue&all=1"' in body and 'href="?s=headlines&all=1"' in body  # rail
    assert 'class="btn btn-sm">← Back' in body and "?s=scorecard&all=1\" class=\"btn btn-sm\">← Back" in body
    assert "?s=headlines&all=1\" class=\"btn btn-sm btn-primary\">Next" in body
    assert 'searchParams.set("all", "1")' in body and "all = true" in body
    assert "all = false" in page(member, meeting, "rocks")


def test_roster_note_links_update_the_url(member, meeting, world):
    body = page(member, meeting, "rocks")
    assert re.search(r'hx-push-url="true" href="\?s=rocks&all=1"', body)


@pytest.mark.parametrize("section", ["rocks", "ids", "todos", "scorecard", "conclude"])
def test_links_to_detail_pages_let_htmx_push_the_url(member, meeting, world, section):
    """The L10 body opts out of pushing history for its own swaps. A link out of it must opt back in, or the
    detail page appears under the meeting's URL and Back skips the section."""
    from todos.models import Todo

    if section == "conclude":
        Todo.objects.filter(pk=world["todos"]["ky"].pk).update(meeting=meeting)
    body = page(member, meeting, section)
    body = body.split('id="l10-body"', 1)[1]
    links = re.findall(r'<a [^>]*href="(?:/rocks/|/issues/|/todos/)\d+[^>]*>', body)
    assert links or section == "scorecard"
    for tag in links:
        assert 'hx-push-url="unset"' in tag or 'hx-boost="false"' in tag, tag
