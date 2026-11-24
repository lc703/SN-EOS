import datetime as dt

from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import people_choices
from core.models import Quarter
from core.permissions import is_admin, is_team_member
from core.scoping import for_team
from core.utils import go_back, is_htmx, require, scope
from issues.models import Issue
from rocks.models import Rock
from rocks.views import rock_summary
from scorecard.models import ScoreEntry
from scorecard.plants import scorecard_for_team
from todos.models import Todo, default_due
from vision.models import VTO, CoreValue

from .models import AGENDAS, ANNUAL, ITEM_KINDS, KIND_CHOICES, QUARTERLY, SECTION_KINDS, Session, SessionItem, SessionRating

KIND_LABELS = dict(ITEM_KINDS)
VTO_FIELDS = ["one_year_date", "one_year_revenue", "one_year_profit", "one_year_measurables", "one_year_goals"]


def can_run(user, session):
    return is_admin(user) or is_team_member(user, session.team)


def next_quarter_for(quarter):
    day = (quarter.end_date if quarter else timezone.localdate()) + dt.timedelta(days=1)
    return Quarter.objects.for_date(day) or Quarter.for_calendar(day)


def sessions_list(request):
    team, _ = scope(request)
    sessions = for_team(Session.objects.all(), team).select_related("team", "quarter", "next_quarter", "facilitator").prefetch_related("ratings", "items")
    return render(request, "planning/sessions.html", {
        "sessions": sessions, "can_run": team is not None and (is_admin(request.user) or is_team_member(request.user, team)),
        "agendas": [(k, label, AGENDAS[k]) for k, label in KIND_CHOICES],
    })


@require_POST
def session_start(request):
    team, quarter = scope(request)
    require(team is not None and (is_admin(request.user) or is_team_member(request.user, team)))
    kind = request.POST.get("kind") if request.POST.get("kind") in dict(KIND_CHOICES) else QUARTERLY
    session = Session.objects.create(
        kind=kind, team=team, quarter=quarter, next_quarter=next_quarter_for(quarter), facilitator=request.user,
    )
    session.attendees.set(team.members.filter(is_active=True))
    return redirect("session", pk=session.pk)


def _items_by_kind(session, section):
    kinds = SECTION_KINDS.get(section, ["note"])
    items = list(session.items.filter(section=section).select_related("author", "about"))
    return [(k, KIND_LABELS[k], [i for i in items if i.kind == k]) for k in kinds]


def section_context(request, session, section):
    team = session.team
    ctx = {"groups": _items_by_kind(session, section)}
    if section == "review" and session.quarter:
        rocks = list(for_team(Rock.objects.filter(quarter=session.quarter), team, extra=Q(is_company=True)).select_related("owner", "team"))
        weeks = session.quarter.weeks()
        site_ms = scorecard_for_team(team)[0]
        entries = ScoreEntry.objects.filter(measurable__in=site_ms, week_start__in=weeks).select_related("measurable")
        judged = [e.on_goal for e in entries if e.on_goal is not None]
        ctx.update(
            rocks=rocks, summary=rock_summary(rocks),
            done_pct=round(100 * sum(r.status == Rock.DONE for r in rocks) / len(rocks)) if rocks else None,
            on_goal_pct=round(100 * sum(judged) / len(judged)) if judged else None,
            measurables=site_ms.count(),
            solved=for_team(Issue.objects.filter(status=Issue.SOLVED, solved_at__date__gte=session.quarter.start_date), team).count(),
        )
    elif section == "team_health":
        ctx["people"] = session.attendees.order_by("name")
    elif section == "vto":
        ctx.update(vto=VTO.load(), values=CoreValue.objects.filter(active=True))
    elif section == "one_year":
        ctx.update(vto=VTO.load(), can_edit_vto=is_admin(request.user))
    elif section == "rocks":
        nq = session.next_quarter
        qs = Rock.objects.filter(quarter=nq).select_related("owner", "team") if nq else Rock.objects.none()
        ctx.update(
            company_rocks=qs.filter(is_company=True), team_rocks=for_team(qs.filter(is_company=False), team),
            people=people_choices(team, include=[request.user.pk]), next_quarter=nq,
        )
    elif section == "ids":
        ctx.update(
            long_issues=for_team(Issue.objects.filter(status=Issue.OPEN, horizon=Issue.LONG), team).select_related("owner"),
            short_issues=for_team(Issue.objects.filter(status=Issue.OPEN, horizon=Issue.SHORT), team).select_related("owner")[:15],
            solved_here=for_team(Issue.objects.filter(status=Issue.SOLVED, solved_at__gte=session.started_at), team).select_related("owner"),
        )
    elif section == "next_steps":
        ctx.update(
            todos=for_team(Todo.objects.filter(created_at__gte=session.started_at, is_private=False), team).select_related("owner"),
            people=people_choices(team, include=[request.user.pk]), default_due=default_due(),
        )
    elif section == "conclude":
        ratings = {r.user_id: r.rating for r in session.ratings.all()}
        ctx.update(
            attendee_ratings=[(u, ratings.get(u.pk)) for u in session.attendees.order_by("name")],
            average=session.average_rating, rating_range=range(1, 11),
            new_rocks=for_team(Rock.objects.filter(quarter=session.next_quarter, created_at__gte=session.started_at), team, extra=Q(is_company=True)).count() if session.next_quarter else 0,
            new_todos=for_team(Todo.objects.filter(created_at__gte=session.started_at), team).count(),
        )
    return ctx


def session_view(request, pk):
    session = get_object_or_404(Session.objects.select_related("team", "quarter", "next_quarter", "facilitator"), pk=pk)
    keys = session.section_keys
    section = request.GET.get("s")
    if section in keys:
        if session.facilitator_id == request.user.pk and section != session.current_section and not session.is_concluded:
            session.current_section = section
            session.save(update_fields=["current_section"])
    else:
        section = session.current_section if session.current_section in keys else keys[0]
    request._team = session.team
    request._quarter = session.quarter
    idx = keys.index(section)
    agenda = session.agenda
    ctx = {
        "session": session, "section": section, "agenda": agenda,
        "section_title": agenda[idx][1], "section_prompt": agenda[idx][2],
        "prev": keys[idx - 1] if idx > 0 else None, "next_s": keys[idx + 1] if idx < len(keys) - 1 else None,
        "can_run": can_run(request.user, session), "notes": (session.section_notes or {}).get(section, ""),
        "colors": SessionItem.COLOR_CHOICES, "hide_scope": True, "wide": True,
        "counts": {k: session.items.filter(section=k).count() for k in keys},
    }
    ctx.update(section_context(request, session, section))
    return render(request, "planning/session.html", ctx)


@require_POST
def item_add(request, pk):
    session = get_object_or_404(Session, pk=pk)
    require(can_run(request.user, session))
    section, kind = request.POST.get("section", ""), request.POST.get("kind", "note")
    text = (request.POST.get("text") or "").strip()
    if section in session.section_keys and kind in KIND_LABELS and text:
        about = session.attendees.filter(pk=request.POST.get("about") or 0).first()
        color = request.POST.get("color", "")
        SessionItem.objects.create(
            session=session, section=section, kind=kind, text=text[:2000], author=request.user, about=about,
            color=color if color in dict(SessionItem.COLOR_CHOICES) else "",
            sort=session.items.filter(section=section, kind=kind).count(),
        )
    return go_back(request, f"/planning/{session.pk}/?s={section}")


@require_POST
def item_update(request, pk):
    item = get_object_or_404(SessionItem.objects.select_related("session"), pk=pk)
    require(can_run(request.user, item.session))
    back = f"/planning/{item.session_id}/?s={item.section}"
    action = request.POST.get("action")
    if action == "delete":
        item.delete()
    elif action == "issue":
        Issue.objects.create(
            team=item.session.team, title=item.text[:240], description=f"From {item.session.get_kind_display()} ({KIND_LABELS.get(item.kind)}).",
            horizon=Issue.LONG if item.session.kind == ANNUAL or item.section == "swot" else Issue.SHORT,
            owner=request.user, created_by=request.user,
        )
        item.legacy = (item.legacy or {}) | {"issue_created": True}
        item.save(update_fields=["legacy"])
        messages.success(request, "Added to the Issues List.")
    elif action == "color":
        color = request.POST.get("color", "")
        item.color = color if color in dict(SessionItem.COLOR_CHOICES) else ""
        item.save(update_fields=["color"])
    return go_back(request, back)


@require_POST
def session_update(request, pk):
    session = get_object_or_404(Session, pk=pk)
    require(can_run(request.user, session))
    section = request.POST.get("section")
    if "notes" in request.POST and section in session.section_keys:
        session.section_notes = (session.section_notes or {}) | {section: request.POST["notes"]}
        session.save(update_fields=["section_notes"])
    if request.POST.get("facilitate"):
        session.facilitator = request.user
        session.save(update_fields=["facilitator"])
    if any(f in request.POST for f in VTO_FIELDS):
        require(is_admin(request.user))
        vto = VTO.load()
        for f in VTO_FIELDS:
            if f in request.POST:
                setattr(vto, f, request.POST[f].strip())
        vto.updated_by = request.user
        vto.save()
    if is_htmx(request):
        return HttpResponse(status=204)
    return go_back(request, f"/planning/{session.pk}/")


@require_POST
def session_rock(request, pk):
    session = get_object_or_404(Session.objects.select_related("team", "next_quarter"), pk=pk)
    require(can_run(request.user, session))
    title = (request.POST.get("title") or "").strip()
    if title and session.next_quarter:
        company = request.POST.get("company") == "1" and (session.team.is_leadership or is_admin(request.user))
        owner = people_choices(session.team, include=[request.user.pk]).filter(pk=request.POST.get("owner") or request.user.pk).first()
        Rock.objects.create(
            quarter=session.next_quarter, team=session.team, is_company=company, title=title[:200], owner=owner,
            sort=Rock.objects.filter(quarter=session.next_quarter, team=session.team).count(),
        )
    return go_back(request, f"/planning/{session.pk}/?s=rocks")


@require_POST
def session_todo(request, pk):
    session = get_object_or_404(Session, pk=pk)
    require(can_run(request.user, session))
    title = (request.POST.get("title") or "").strip()
    if title:
        owner = people_choices(session.team, include=[request.user.pk]).filter(pk=request.POST.get("owner") or request.user.pk).first() or request.user
        due = request.POST.get("due_date") or default_due()
        Todo.objects.create(team=session.team, title=title[:240], owner=owner, due_date=due, created_by=request.user)
    return go_back(request, f"/planning/{session.pk}/?s=next_steps")


@require_POST
def session_rate(request, pk):
    session = get_object_or_404(Session, pk=pk)
    user_id = int(request.POST.get("user") or request.user.pk)
    require(user_id == request.user.pk or session.facilitator_id == request.user.pk or is_admin(request.user))
    raw = request.POST.get("rating")
    rating = int(raw) if raw and raw.isdigit() and 1 <= int(raw) <= 10 else None
    SessionRating.objects.update_or_create(session=session, user_id=user_id, defaults={"rating": rating})
    return go_back(request, f"/planning/{session.pk}/?s=conclude")


@require_POST
def session_conclude(request, pk):
    session = get_object_or_404(Session, pk=pk)
    require(can_run(request.user, session))
    if request.POST.get("reopen"):
        session.concluded_at = None
    else:
        session.concluded_at = timezone.now()
        session.current_section = "conclude"
        messages.success(request, f"{session.get_kind_display()} concluded. The recap is ready to print or share.")
    session.save(update_fields=["concluded_at", "current_section"])
    return redirect("session_recap", pk=session.pk) if session.concluded_at else redirect("session", pk=session.pk)


def session_recap(request, pk):
    session = get_object_or_404(Session.objects.select_related("team", "quarter", "next_quarter", "facilitator"), pk=pk)
    request._team = session.team
    sections = []
    for key, title, _ in session.agenda:
        groups = [g for g in _items_by_kind(session, key) if g[2]]
        note = (session.section_notes or {}).get(key, "")
        if groups or note:
            sections.append({"title": title, "groups": groups, "notes": note})
    rocks = Rock.objects.filter(quarter=session.next_quarter).filter(Q(team=session.team) | Q(is_company=True)).select_related("owner") if session.next_quarter else []
    return render(request, "planning/recap.html", {
        "session": session, "sections": sections, "rocks": rocks,
        "todos": Todo.objects.filter(team=session.team, created_at__gte=session.started_at, is_private=False).select_related("owner"),
        "ratings": session.ratings.select_related("user"), "hide_scope": True,
    })
