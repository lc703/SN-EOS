import json

from people.models import OneOnOne, OneOnOneScore, PeopleReview, SuccessStatement
from vision.models import Seat


def _tree(teams, ky_peer, member):
    boss = Seat.objects.create(team=teams["ky"], title="Plant Manager", person=ky_peer, roles="a\nb")
    lead = Seat.objects.create(team=teams["ky"], title="Line Lead", person=member, parent=boss)
    tech = Seat.objects.create(team=teams["ky"], title="Tech", parent=lead, status=Seat.FUTURE)
    hire = Seat.objects.create(team=teams["ky"], title="Maintenance", parent=boss)
    return boss, lead, tech, hire


def test_chart_shows_status_colors_and_open_seat_counts(as_user, admin, teams, ky_peer, member):
    _tree(teams, ky_peer, member)
    r = as_user(admin, teams["ky"]).get("/chart/")
    html = r.content.decode()
    assert r.context["counts"] == {"filled": 2, "future": 1, "open": 1}
    assert "st-future" in html and "st-open" in html and "Open, hiring" in html
    assert 'data-chart="fit"' in html and 'data-chart="titles"' in html


def test_chart_canvas_partial_and_list_view(as_user, admin, teams, ky_peer, member):
    _tree(teams, ky_peer, member)
    c = as_user(admin, teams["ky"])
    partial = c.get("/chart/?partial=canvas").content.decode()
    assert partial.lstrip().startswith('<div id="chart-canvas"') and "<html" not in partial
    assert "Maintenance" in c.get("/chart/?view=list").content.decode()


def test_move_reparents_and_blocks_cycles(as_user, admin, member, teams, ky_peer):
    boss, lead, tech, hire = _tree(teams, ky_peer, member)
    c = as_user(admin, teams["ky"])
    r = c.post(f"/chart/seats/{tech.pk}/move/", {"parent": hire.pk}, HTTP_HX_REQUEST="true")
    assert r.status_code == 204 and "chartChanged" in json.loads(r["HX-Trigger"])
    tech.refresh_from_db()
    assert tech.parent == hire
    assert c.post(f"/chart/seats/{boss.pk}/move/", {"parent": lead.pk}).status_code == 422
    assert c.post(f"/chart/seats/{boss.pk}/move/", {"parent": boss.pk}).status_code == 422
    boss.refresh_from_db()
    assert boss.parent is None
    assert as_user(member).post(f"/chart/seats/{tech.pk}/move/", {"parent": ""}).status_code == 403


def test_panel_autosave_and_create(as_user, admin, teams, ky_peer, member):
    boss, lead, *_ = _tree(teams, ky_peer, member)
    c = as_user(admin, teams["ky"])
    assert "Changes save automatically" in c.get(f"/chart/seats/{lead.pk}/panel/").content.decode()
    data = {"title": "Line Lead (days)", "person": member.pk, "status": "filled", "is_agency": "on", "parent": boss.pk, "team": teams["ky"].pk, "roles": "", "autosave": "1"}
    r = c.post(f"/chart/seats/{lead.pk}/", data, HTTP_HX_REQUEST="true")
    assert r.status_code == 204
    lead.refresh_from_db()
    assert lead.title == "Line Lead (days)" and lead.is_agency
    bad = c.post(f"/chart/seats/{lead.pk}/", {**data, "title": ""}, HTTP_HX_REQUEST="true")
    assert bad.status_code == 422 and "toast" in json.loads(bad["HX-Trigger"])
    new = c.post("/chart/seats/new/", {"title": "Shipping", "parent": boss.pk, "team": teams["ky"].pk, "status": "open"}, HTTP_HX_REQUEST="true")
    assert new.status_code == 200 and Seat.objects.get(title="Shipping").status == "open"


def test_member_sees_read_only_panel(as_user, member, teams, ky_peer):
    boss, lead, *_ = _tree(teams, ky_peer, member)
    html = as_user(member).get(f"/chart/seats/{boss.pk}/panel/").content.decode()
    assert "Changes save automatically" not in html and "Roles" in html


def test_people_flags_respect_privacy(as_user, admin, member, other, teams, ky_peer):
    boss, lead, *_ = _tree(teams, ky_peer, member)
    PeopleReview.objects.create(person=member, reviewer=ky_peer, gets_it=True, wants_it=True, capacity=False)
    s = SuccessStatement.objects.create(person=member, text="Line runs")
    o = OneOnOne.objects.create(person=member, manager=ky_peer)
    OneOnOneScore.objects.create(one_on_one=o, statement=s, rag="red")
    for viewer in (admin, ky_peer, member):
        html = as_user(viewer, teams["ky"]).get("/chart/").content.decode()
        assert "1 red in 1:1" in html and "GWC from the latest People Analyzer" in html
    html = as_user(other, teams["ky"]).get("/chart/").content.decode()
    assert "1 red in 1:1" not in html and "GWC from the latest People Analyzer" not in html
