"""Issues are tagged by site: a chip everywhere, a Site select on create/edit, and a site filter on Company."""

import re

import pytest
from django.utils import timezone

from issues.models import Issue
from meetings.models import Meeting
from rocks.models import Rock
from todos.models import Todo
from tests.conftest import client_for
from tests.test_rollup import all_teams, cur_q, get, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


def chips(body):
    return re.findall(r'site-chip" title="Site">([^<]+)<', body)


def issue_row(body, issue):
    return re.search(rf'id="issue-{issue.pk}".*?(?=id="issue-\d+"|</body>)', body, re.S).group(0)


def test_every_issue_row_has_a_site_chip_on_a_site_view_too(member, all_teams, world):
    body = get(member, "/issues/", all_teams["ky"]).content.decode()
    assert "Kentucky" in re.search(r'id="issue-\d+".*?</div>\s*</div>\s*</div>', body, re.S).group(0)
    assert chips(body).count("Kentucky") >= 1


def test_company_view_chips_name_each_site_in_short_and_long_lists(admin, all_teams, world):
    Issue.objects.create(team=all_teams["lr"], title="Long one", horizon=Issue.LONG, owner=admin)
    short = get(admin, "/issues/", all_teams["company"]).content.decode()
    assert set(chips(short)) >= {"Company", "Kentucky", "Le Roy", "Mabel"}
    long = get(admin, "/issues/?list=long", all_teams["company"]).content.decode()
    assert "Long one" in long and "Le Roy" in issue_row(long, Issue.objects.get(title="Long one"))


def test_l10_ids_section_shows_the_chip_on_site_and_company_meetings(admin, member, all_teams, world, cur_q):
    for key, user in (("company", admin), ("ky", member)):
        m = Meeting.objects.create(team=all_teams[key], quarter=cur_q, date=timezone.localdate())
        m.attendees.add(user)
        body = client_for(user).get(f"/meetings/{m.pk}/?s=ids&all=1").content.decode()
        assert "Kentucky" in chips(body)
    assert "Mabel" in chips(client_for(admin).get(f"/meetings/{m.pk - 1}/?s=ids&all=1").content.decode())


def test_issue_detail_shows_the_site_chip(member, all_teams, world):
    body = get(member, f"/issues/{world['issues']['ky'].pk}/").content.decode()
    assert "Kentucky" in chips(body)


def test_todos_and_rocks_show_chips_on_site_views_too(member, all_teams, world):
    assert "Kentucky" in chips(get(member, "/todos/", all_teams["ky"]).content.decode())
    assert "Kentucky" in chips(get(member, "/rocks/", all_teams["ky"]).content.decode())


def test_create_form_has_a_site_select_defaulting_to_the_current_team(member, admin, all_teams, world):
    body = get(member, "/issues/", all_teams["ky"]).content.decode()
    sel = re.search(r'<select name="team".*?</select>', body, re.S).group(0)
    assert re.search(rf'<option value="{all_teams["ky"].pk}" selected>Kentucky', sel)
    co = re.search(r'<select name="team".*?</select>', get(admin, "/issues/", all_teams["company"]).content.decode(), re.S).group(0)
    assert re.search(rf'<option value="{all_teams["company"].pk}" selected>Company', co)


def test_create_files_under_the_chosen_site_and_defaults_to_the_current_team(admin, all_teams, world):
    c = client_for(admin, all_teams["company"])
    c.post("/issues/new/", {"title": "To Mabel", "team": all_teams["mabel"].pk, "horizon": Issue.SHORT})
    c.post("/issues/new/", {"title": "No site given", "horizon": Issue.SHORT})
    assert Issue.objects.get(title="To Mabel").team == all_teams["mabel"]
    assert Issue.objects.get(title="No site given").team == all_teams["company"]


def test_a_member_cannot_file_an_issue_on_a_site_they_are_not_on(member, all_teams, world):
    client_for(member, all_teams["ky"]).post("/issues/new/", {"title": "Sneaky", "team": all_teams["lr"].pk, "horizon": Issue.SHORT})
    assert not Issue.objects.filter(title="Sneaky").exists()


def test_edit_form_has_a_site_select_and_changing_it_moves_the_issue(admin, all_teams, world):
    issue = world["issues"]["ky"]
    page = get(admin, f"/issues/{issue.pk}/").content.decode()
    assert re.search(r'<select name="team"', page) and ">Site<" in page
    r = client_for(admin).post(f"/issues/{issue.pk}/", {
        "title": issue.title, "team": all_teams["lr"].pk, "owner": issue.owner_id or "", "horizon": issue.horizon, "description": "",
    })
    assert r.status_code == 302
    issue.refresh_from_db()
    assert issue.team == all_teams["lr"]
    assert issue.title in get(admin, "/issues/", all_teams["lr"]).content.decode()
    assert issue.title not in get(admin, "/issues/", all_teams["ky"]).content.decode()


def _edit(user, issue, team):
    return client_for(user).post(f"/issues/{issue.pk}/", {
        "title": issue.title, "team": team.pk, "owner": issue.owner_id or "", "horizon": issue.horizon, "description": "",
    })


def test_moving_keeps_the_rank_when_free_and_clears_it_when_taken(admin, all_teams, world):
    ky, lr = world["issues"]["ky"], world["issues"]["lr"]
    ky.set_priority(1)
    _edit(admin, ky, all_teams["mabel"])
    ky.refresh_from_db()
    assert ky.team == all_teams["mabel"] and ky.priority == 1

    lr.set_priority(2)
    ky.set_priority(2)
    _edit(admin, ky, all_teams["lr"])
    ky.refresh_from_db(), lr.refresh_from_db()
    assert ky.team == all_teams["lr"] and ky.priority is None and lr.priority == 2
    ranks = Issue.objects.filter(team=all_teams["lr"], horizon=Issue.SHORT, status=Issue.OPEN, priority__isnull=False)
    assert [i.priority for i in ranks] == [2]


def test_a_member_cannot_move_an_issue_to_a_site_they_are_not_on(member, all_teams, world):
    issue = world["issues"]["ky"]
    _edit(member, issue, all_teams["lr"])
    issue.refresh_from_db()
    assert issue.team == all_teams["ky"]


def test_saving_without_a_site_field_keeps_the_issue_where_it_is(admin, all_teams, world):
    issue = world["issues"]["ky"]
    client_for(admin).post(f"/issues/{issue.pk}/", {"title": "Renamed", "owner": "", "horizon": issue.horizon, "description": ""})
    issue.refresh_from_db()
    assert issue.title == "Renamed" and issue.team == all_teams["ky"]


def test_company_site_filter(admin, all_teams, world):
    c = client_for(admin, all_teams["company"])
    body = c.get("/issues/").content.decode()
    assert 'id="site-filter"' in body and all(f">{n}</a>" in body for n in ("All", "Company", "Kentucky", "Le Roy", "Mabel"))
    for key, slug in (("ky", "kentucky"), ("lr", "le-roy"), ("mabel", "mabel"), ("company", "company")):
        page = c.get(f"/issues/?site={slug}").content.decode()
        assert f"Issue {key}" in page
        assert all(f"Issue {k}" not in page for k in ("company", "ky", "lr", "mabel") if k != key)
    allp = c.get("/issues/?site=all").content.decode()
    assert all(f"Issue {k}" in allp for k in ("company", "ky", "lr", "mabel"))
    long = c.get("/issues/?list=long&site=kentucky").content.decode()
    assert "list=short&site=kentucky" in long


def test_site_filter_is_not_offered_on_a_site_view_and_cannot_widen_it(member, all_teams, world):
    body = client_for(member, all_teams["ky"]).get("/issues/?site=mabel").content.decode()
    assert 'id="site-filter"' not in body and "Issue mabel" not in body and "Issue ky" in body


# ---- deleting issues ---------------------------------------------------------------------------------

def _delete(user, issue, **extra):
    return client_for(user).post(f"/issues/{issue.pk}/delete/", extra)


def test_delete_is_post_only_and_csrf_protected(admin, all_teams, world):
    from django.test import Client
    issue = world["issues"]["ky"]
    c = client_for(admin)
    assert c.get(f"/issues/{issue.pk}/delete/").status_code == 405
    assert Issue.objects.filter(pk=issue.pk).exists()
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(admin)
    assert strict.post(f"/issues/{issue.pk}/delete/").status_code == 403
    assert Issue.objects.filter(pk=issue.pk).exists()


def test_owner_team_member_and_admin_can_delete_others_cannot(admin, member, other, ky_peer, all_teams, world):
    mine = Issue.objects.create(team=all_teams["lr"], title="Owned by Kim", owner=member)
    assert _delete(member, mine).status_code == 302          # owner, though not on the team
    assert not Issue.objects.filter(pk=mine.pk).exists()
    ky = world["issues"]["ky"]                                # owned by Kim, KY team
    assert _delete(other, ky).status_code == 403              # on Le Roy only
    assert Issue.objects.filter(pk=ky.pk).exists()
    peer_issue = Issue.objects.create(team=all_teams["ky"], title="Team issue", owner=admin)
    assert _delete(ky_peer, peer_issue).status_code == 302    # team member
    lr = world["issues"]["lr"]
    assert _delete(admin, lr).status_code == 302              # admin
    assert not Issue.objects.filter(pk=lr.pk).exists()


def test_every_row_has_a_confirmed_delete_button(member, all_teams, world):
    body = get(member, "/issues/", all_teams["ky"]).content.decode()
    issue = world["issues"]["ky"]
    btn = re.search(rf'<button[^>]*hx-post="/issues/{issue.pk}/delete/"[^>]*>', body).group(0)
    assert "hx-confirm=" in btn and f'hx-target="#issue-{issue.pk}"' in btn and "hx-swap=\"outerHTML\"" in btn
    long = Issue.objects.create(team=all_teams["ky"], title="A long one", horizon=Issue.LONG, owner=member)
    assert f"/issues/{long.pk}/delete/" in get(member, "/issues/?list=long", all_teams["ky"]).content.decode()


def test_l10_ids_rows_and_detail_page_have_delete(admin, member, all_teams, world, cur_q):
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate())
    meeting.attendees.add(member)
    issue = world["issues"]["ky"]
    ids = client_for(member).get(f"/meetings/{meeting.pk}/?s=ids").content.decode()
    assert f'hx-post="/issues/{issue.pk}/delete/"' in ids
    detail = get(member, f"/issues/{issue.pk}/").content.decode()
    assert f'formaction="/issues/{issue.pk}/delete/"' in detail and "confirm(" in detail


def test_htmx_delete_returns_an_empty_swap_and_removes_the_row(admin, all_teams, world, cur_q):
    issue = world["issues"]["ky"]
    r = client_for(admin).post(f"/issues/{issue.pk}/delete/", HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and r.content == b"" and "HX-Refresh" not in r
    assert not Issue.objects.filter(pk=issue.pk).exists()


def test_list_delete_refreshes_so_counts_and_ranks_stay_right(admin, all_teams, world):
    issue = world["issues"]["lr"]
    r = client_for(admin).post(f"/issues/{issue.pk}/delete/", {"refresh": "1"}, HTTP_HX_REQUEST="true")
    assert r.headers.get("HX-Refresh") == "true"


def test_plain_post_redirects_back_to_the_list_never_to_the_deleted_page(admin, all_teams, world):
    issue = world["issues"]["ky"]
    r = client_for(admin).post(f"/issues/{issue.pk}/delete/", HTTP_REFERER=f"http://testserver/issues/{issue.pk}/")
    assert r.status_code == 302 and r["Location"] == "/issues/"
    assert client_for(admin).get(r["Location"]).status_code == 200


def test_deleting_a_ranked_issue_recompacts_the_ranks(admin, all_teams, world):
    team = all_teams["ky"]
    a = Issue.objects.create(team=team, title="A", owner=admin)
    b = Issue.objects.create(team=team, title="B", owner=admin)
    c = Issue.objects.create(team=team, title="C", owner=admin)
    other_team = Issue.objects.create(team=all_teams["lr"], title="Elsewhere", owner=admin)
    a.set_priority(1), b.set_priority(2), c.set_priority(3), other_team.set_priority(2)
    r = client_for(admin).post(f"/issues/{a.pk}/delete/", HTTP_HX_REQUEST="true")
    assert r.headers.get("HX-Refresh") == "true"
    b.refresh_from_db(), c.refresh_from_db(), other_team.refresh_from_db()
    assert (b.priority, c.priority, other_team.priority) == (1, 2, 2)
    client_for(admin).post(f"/issues/{c.pk}/delete/")
    b.refresh_from_db()
    assert b.priority == 1


def test_deleting_an_unranked_issue_leaves_ranks_alone(admin, all_teams, world):
    team = all_teams["mabel"]
    ranked = Issue.objects.create(team=team, title="R", owner=admin)
    ranked.set_priority(2)
    plain = Issue.objects.create(team=team, title="P", owner=admin)
    client_for(admin).post(f"/issues/{plain.pk}/delete/")
    ranked.refresh_from_db()
    assert ranked.priority == 2


def test_related_records_survive_a_delete(admin, all_teams, world, cur_q):
    issue = world["issues"]["ky"]
    meeting = Meeting.objects.create(team=all_teams["ky"], quarter=cur_q, date=timezone.localdate())
    issue.raised_meeting = issue.solved_meeting = meeting
    issue.save()
    todo = Todo.objects.create(team=all_teams["ky"], title="From the issue", owner=admin, issue=issue, meeting=meeting,
                               asana_task_gid="123", asana_sent_at=timezone.now())
    client_for(admin).post(f"/issues/{issue.pk}/delete/")
    todo.refresh_from_db()
    assert todo.issue_id is None and todo.asana_task_gid == "123" and todo.asana_sent_at and todo.meeting_id == meeting.pk
    assert Meeting.objects.filter(pk=meeting.pk).exists()
    assert client_for(admin).get(f"/meetings/{meeting.pk}/?s=conclude").status_code == 200
    assert client_for(admin).get(f"/todos/{todo.pk}/").status_code == 200


def test_issue_detail_form_delete_button_no_longer_posts_the_edit_form(admin, all_teams, world):
    issue = world["issues"]["ky"]
    r = client_for(admin).post(f"/issues/{issue.pk}/", {"delete": "1"})
    assert r.status_code == 302 and not Issue.objects.filter(pk=issue.pk).exists()


# ---- raising an issue from inside an L10 --------------------------------------------------------------

def _add_form(body):
    """The add-issue form exactly as the browser would submit it (hidden inputs and selected options)."""
    from html import unescape
    form = re.search(r'<form[^>]*action="/issues/new/".*?</form>', body, re.S).group(0)
    data = {}
    for tag in re.findall(r"<input[^>]*>", form):
        name, value = re.search(r'name="(\w+)"', tag), re.search(r'value="([^"]*)"', tag)
        if name:
            data[name.group(1)] = unescape(value.group(1)) if value else ""
    for sel in re.finditer(r'<select name="(\w+)"(.*?)</select>', form, re.S):
        picked = re.search(r'value="(\d+)" selected', sel.group(2))
        if picked:
            data[sel.group(1)] = picked.group(1)
    return form, data


def _meeting(team, cur_q, facilitator=None):
    m = Meeting.objects.create(team=team, quarter=cur_q, date=timezone.localdate(), facilitator=facilitator, current_section="ids")
    return m


@pytest.mark.parametrize("session_site", ["ky", "company", "lr"])
def test_l10_add_issue_lands_on_that_meetings_ids_list(member, all_teams, world, cur_q, session_site):
    """Regression: the add form used the session's current site, so a member whose session was on another
    site got a silent 403 (htmx doesn't swap errors) and nothing appeared in the IDS list."""
    meeting = _meeting(all_teams["ky"], cur_q, member)
    c = client_for(member, all_teams[session_site])
    _, data = _add_form(c.get(f"/meetings/{meeting.pk}/?s=ids").content.decode())
    assert data["meeting"] == str(meeting.pk) and data["horizon"] == "short"
    r = c.post("/issues/new/", {**data, "title": "Raised in the L10"})
    assert r.status_code == 302 and r["Location"] == f"/meetings/{meeting.pk}/?s=ids"
    issue = Issue.objects.get(title="Raised in the L10")
    assert (issue.team, issue.horizon, issue.status, issue.raised_meeting) == (all_teams["ky"], Issue.SHORT, Issue.OPEN, meeting)
    assert issue.created_by == member
    page = c.get(r["Location"]).content.decode()
    assert "Raised in the L10" in page and f'id="issue-{issue.pk}"' in page
    assert "Raised in the L10" not in get(member, "/issues/?list=long", all_teams["ky"]).content.decode()


def test_site_meeting_form_pins_the_site_and_the_server_enforces_it(member, all_teams, world, cur_q):
    meeting = _meeting(all_teams["ky"], cur_q, member)
    c = client_for(member, all_teams["company"])
    form, data = _add_form(c.get(f"/meetings/{meeting.pk}/?s=ids").content.decode())
    assert 'aria-label="Site"' not in form and data["team"] == str(all_teams["ky"].pk)
    c.post("/issues/new/", {**data, "title": "Tampered", "team": all_teams["lr"].pk, "horizon": "long"})
    issue = Issue.objects.get(title="Tampered")
    assert (issue.team, issue.horizon) == (all_teams["ky"], Issue.SHORT)


def test_company_meeting_keeps_the_site_select_and_shows_every_site(admin, all_teams, world, cur_q):
    meeting = _meeting(all_teams["company"], cur_q, admin)
    c = client_for(admin, all_teams["ky"])
    form, data = _add_form(c.get(f"/meetings/{meeting.pk}/?s=ids").content.decode())
    assert 'aria-label="Site"' in form and data["team"] == str(all_teams["company"].pk)
    c.post("/issues/new/", {**data, "title": "Company-wide"})
    c.post("/issues/new/", {**data, "title": "Le Roy only", "team": all_teams["lr"].pk, "horizon": "long"})
    assert Issue.objects.get(title="Company-wide").team == all_teams["company"]
    lr = Issue.objects.get(title="Le Roy only")
    assert (lr.team, lr.horizon) == (all_teams["lr"], Issue.SHORT)
    page = c.get(f"/meetings/{meeting.pk}/?s=ids").content.decode()
    assert "Company-wide" in page and "Le Roy only" in page


def test_l10_add_issue_needs_membership_of_the_meetings_team(other, all_teams, world, cur_q):
    meeting = _meeting(all_teams["ky"], cur_q)
    r = client_for(other, all_teams["lr"]).post("/issues/new/", {"title": "Nope", "meeting": meeting.pk, "team": all_teams["ky"].pk})
    assert r.status_code == 403 and not Issue.objects.filter(title="Nope").exists()


def test_garbage_meeting_id_is_ignored_not_a_crash(member, all_teams, world, cur_q):
    r = client_for(member, all_teams["ky"]).post("/issues/new/", {"title": "Plain", "horizon": "short", "meeting": "abc", "team": all_teams["ky"].pk})
    assert r.status_code == 302 and Issue.objects.get(title="Plain").raised_meeting is None
