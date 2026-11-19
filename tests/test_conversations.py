import pytest

from people.models import OneOnOne, OneOnOneScore, SuccessStatement
from vision.models import CoreValue, Seat

pytestmark = pytest.mark.django_db

HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def chart(teams, member, ky_peer):
    """ky_peer manages member."""
    boss = Seat.objects.create(team=teams["ky"], title="Plant Manager", person=ky_peer)
    Seat.objects.create(team=teams["ky"], title="Production Lead", person=member, parent=boss)
    return boss


@pytest.fixture
def statement(member):
    return SuccessStatement.objects.create(person=member, text="Mill runs at 95% uptime")


def test_tracker_lists_pairs_and_completion(as_user, teams, ky_peer, member, chart, quarter):
    c = as_user(ky_peer, teams["ky"])
    html = c.get("/people/conversations/").content.decode()
    assert "Kim Member" in html and "Not started" in html
    c.post(f"/people/{member.pk}/conversations/start/")
    o = OneOnOne.objects.get()
    assert o.kind == OneOnOne.QUARTERLY and o.manager == ky_peer
    o.completed_at = o.created_at
    o.save()
    html = c.get("/people/conversations/").content.decode()
    assert "100%" in html


def test_start_reuses_this_quarters_conversation(as_user, teams, ky_peer, member, chart, quarter):
    c = as_user(ky_peer, teams["ky"])
    c.post(f"/people/{member.pk}/conversations/start/")
    r = c.post(f"/people/{member.pk}/conversations/start/")
    assert OneOnOne.objects.count() == 1
    assert r.url == f"/conversations/{OneOnOne.objects.get().pk}/"


def test_grid_scores_toggle_and_notes(as_user, teams, ky_peer, member, chart, statement, quarter):
    value = CoreValue.objects.create(name="Own it")
    o = OneOnOne.objects.create(person=member, manager=ky_peer)
    c = as_user(ky_peer, teams["ky"])
    page = c.get(f"/conversations/{o.pk}/").content.decode()
    assert "Mill runs at 95% uptime" in page and "Own it" in page
    assert c.post(f"/conversations/{o.pk}/score/", {"kind": "ss", "ref": statement.pk, "rag": "red"}, **HX).status_code == 204
    c.post(f"/conversations/{o.pk}/score/", {"kind": "ss", "ref": statement.pk, "note": "Plan: rebuild hammer mill"}, **HX)
    c.post(f"/conversations/{o.pk}/score/", {"kind": "cv", "ref": value.pk, "rag": "green"}, **HX)
    s = OneOnOneScore.objects.get(statement=statement)
    assert s.rag == "red" and s.note == "Plan: rebuild hammer mill"
    assert o.red_count == 1
    c.post(f"/conversations/{o.pk}/score/", {"kind": "ss", "ref": statement.pk, "rag": "red"}, **HX)
    assert OneOnOneScore.objects.get(statement=statement).rag == ""


def test_red_flags_seat_on_chart(as_user, teams, ky_peer, member, chart, statement):
    o = OneOnOne.objects.create(person=member, manager=ky_peer)
    as_user(ky_peer).post(f"/conversations/{o.pk}/score/", {"kind": "ss", "ref": statement.pk, "rag": "red"}, **HX)
    html = as_user(ky_peer, teams["ky"]).get("/chart/").content.decode()
    assert "1 red in 1:1" in html


def test_highlight_autosave_and_complete(as_user, teams, ky_peer, member, chart):
    o = OneOnOne.objects.create(person=member, manager=ky_peer)
    c = as_user(ky_peer, teams["ky"])
    assert c.post(f"/conversations/{o.pk}/", {"highlight": "Great quarter"}, **HX).status_code == 204
    c.post(f"/conversations/{o.pk}/", {"complete": "1"})
    o.refresh_from_db()
    assert o.highlight == "Great quarter" and o.is_complete


def test_conversations_are_private(as_user, teams, ky_peer, member, other, chart, statement):
    o = OneOnOne.objects.create(person=member, manager=ky_peer)
    c = as_user(other, teams["lr"])
    assert c.get(f"/conversations/{o.pk}/").status_code == 403
    assert c.post(f"/conversations/{o.pk}/score/", {"kind": "ss", "ref": statement.pk, "rag": "green"}).status_code == 403
    assert c.post(f"/people/{member.pk}/conversations/start/").status_code == 403
    assert "Kim Member" not in c.get("/people/conversations/").content.decode()


def test_manager_edits_success_statements(as_user, teams, ky_peer, member, chart):
    c = as_user(ky_peer, teams["ky"])
    c.post(f"/people/{member.pk}/statements/", {"text": "Zero recordables"})
    s = SuccessStatement.objects.get()
    assert s.person == member
    assert as_user(member).post(f"/statements/{s.pk}/delete/").status_code == 403
    c.post(f"/statements/{s.pk}/delete/")
    assert not SuccessStatement.objects.exists()


def test_quick_notes_are_checkins_not_quarterlies(as_user, teams, ky_peer, member, chart):
    as_user(ky_peer).post(f"/people/{member.pk}/one-on-ones/", {"notes": "Talked about shifts"})
    assert OneOnOne.objects.get().kind == OneOnOne.CHECKIN
