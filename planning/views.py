import datetime as dt

from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import people_choices
from core.models import Quarter, User, monday_of
from core.permissions import is_admin, is_team_member
from core.utils import hx_trigger, is_htmx, require, scope
from issues.models import Issue
from rocks.models import Rock
from rocks.views import rock_summary, summary_donut
from scorecard.models import Measurable
from scorecard.views import build_rows, week_summary
from todos.models import Todo, default_due, weekly_completion
from todos.views import TodoForm
from vision.models import VTO, CoreValue, Goal

from .agendas import STEP_ITEMS
from .models import Session, SessionItem, SessionRating


def can_run(user, session):
    return is_admin(user) or is_team_member(user, session.team)


def changed(message=None, kind=None):
    return hx_trigger(HttpResponse(status=204), toast=message, kind=kind, sessionChanged=True)


def next_quarter(after):
    day = (after.end_date if after else timezone.localdate()) + dt.timedelta(days=1)
    return Quarter.objects.filter(start_date__lte=day, end_date__gte=day).first() or Quarter.for_calendar(day)


def sessions_list(request):
    team, quarter = scope(request)
    sessions = list(Session.objects.filter(team=team).select_related("quarter", "facilitator").prefetch_related("ratings", "attendees")) if team else []
    upcoming = next((s for s in reversed(sessions) if not s.is_concluded), None)
    quarters = Quarter.objects.order_by("-start_date")[:8]
    return render(request, "planning/list.html", {
        "sessions": sessions, "upcoming": upcoming, "quarters": quarters,
        "default_quarter": next_quarter(quarter), "can_run": is_admin(request.user) or is_team_member(request.user, team),
        "today": timezone.localdate(),
    })


@require_POST
def session_new(request):
    team, quarter = scope(request)
    require(is_admin(request.user) or is_team_member(request.user, team))
    kind = request.POST.get("kind") if request.POST.get("kind") in dict(Session.KIND_CHOICES) else Session.QUARTERLY
    planned = Quarter.objects.filter(pk=request.POST.get("quarter") or 0).first() or next_quarter(quarter)
    s = Session.objects.create(team=team, quarter=planned, kind=kind, date=request.POST.get("date") or timezone.localdate(), facilitator=request.user)
    s.attendees.set(team.members.filter(is_active=True))
    return redirect("session", pk=s.pk)


def previous_quarter(session):
    if not session.quarter:
        return None
    return Quarter.objects.filter(end_date__lt=session.quarter.start_date).order_by("-end_date").first()


def boards(session, step):
    items = list(session.items.filter(step=step).select_related("author"))
    return [
        {"kind": kind, "label": label, "placeholder": placeholder, "items": [i for i in items if i.kind == kind]}
        for kind, label, placeholder in STEP_ITEMS.get(step, [])
    ]


def step_context(request, session, step):
    team = session.team
    ctx = {"boards": boards(session, step)}
    planned = session.quarter
    if step == "review":
        prev = previous_quarter(session) if session.kind == Session.QUARTERLY else None
        span = (prev.start_date, prev.end_date) if prev else (session.date - dt.timedelta(days=365), session.date)
        qs = Rock.objects.filter(quarter__end_date__gte=span[0], quarter__start_date__lte=span[1]).select_related("owner").prefetch_related("updates")
        rocks = list((qs.filter(is_company=True) if team.is_leadership else qs.filter(team=team)).select_related("quarter"))
        today = timezone.localdate()
        for r in rocks:
            r.in_progress = r.status != Rock.DONE and r.quarter.end_date >= today
        summary = rock_summary(rocks)
        finished = [r for r in rocks if not r.in_progress]
        last_monday = monday_of(min(span[1], timezone.localdate())) - dt.timedelta(weeks=1)
        weeks = prev.weeks() if prev else [last_monday - dt.timedelta(weeks=i) for i in range(51, -1, -1)]
        rows = build_rows(Measurable.objects.filter(team=team, active=True).select_related("owner", "team"), weeks, request.user) if weeks else []
        sc = week_summary(rows, weeks)
        scored = [s for s in sc if s["scored"]]
        todo = weekly_completion(Todo.objects.filter(team=team, is_private=False), weeks=13, today=span[1])
        due = [(d, t) for _, _, d, t in todo if t]
        ctx.update(
            review_label=prev.name if prev else "the last 12 months", rocks=rocks, summary=summary, donut=summary_donut(summary),
            rock_pct=round(100 * summary["done"] / len(finished)) if finished else None,
            rocks_open=len(rocks) - len(finished),
            sc_pct=round(100 * sum(s["on"] for s in scored) / sum(s["scored"] for s in scored)) if scored else None,
            todo_pct=round(100 * sum(d for d, _ in due) / sum(t for _, t in due)) if due else None,
            goals=Goal.objects.all() if session.kind == Session.ANNUAL else [],
        )
    elif step == "vto":
        ctx.update(vto=VTO.load(), values=CoreValue.objects.filter(active=True), goals=Goal.objects.select_related("owner"))
    elif step == "goals":
        ctx.update(goals=Goal.objects.select_related("owner").annotate(n_rocks=Count("rocks")), people=people_choices(team, include=[request.user.pk]))
    elif step == "rocks":
        qs = Rock.objects.filter(quarter=planned).select_related("owner", "goal").prefetch_related("milestones", "updates") if planned else Rock.objects.none()
        ctx.update(
            rocks=list(qs.filter(is_company=True) if team.is_leadership else qs.filter(team=team)),
            people=people_choices(team, include=[request.user.pk]), goals=Goal.objects.filter(done=False),
        )
    elif step == "ids":
        ctx.update(
            issues=Issue.objects.filter(team=team, status=Issue.OPEN).select_related("owner").prefetch_related("todos").order_by("horizon", "-created_at"),
            people=people_choices(team, include=[request.user.pk]), default_due=default_due(), horizon=Issue.LONG, can_edit=True,
        )
    elif step == "next":
        ctx.update(
            new_todos=Todo.objects.filter(team=team, created_at__gte=timezone.make_aware(dt.datetime.combine(session.date, dt.time.min))).select_related("owner")[:30],
            form=TodoForm(team=team, user=request.user),
        )
    elif step == "conclude":
        ratings = {r.user_id: r.rating for r in session.ratings.all()}
        rocks = Rock.objects.filter(quarter=planned, team=team) if planned else []
        ctx.update(
            attendee_ratings=[(u, ratings.get(u.pk)) for u in session.attendees.order_by("name")],
            rated=sum(1 for v in ratings.values() if v), average=session.average_rating, rating_range=range(1, 11),
            rocks_set=len(rocks), goals_set=Goal.objects.filter(done=False).count() if session.kind == Session.ANNUAL else None,
        )
    elif step in ("segue", "health"):
        ctx["members"] = people_choices(team, include=list(session.attendees.values_list("pk", flat=True)))
        ctx["attendee_ids"] = set(session.attendees.values_list("pk", flat=True))
    return ctx


def session_view(request, pk):
    session = get_object_or_404(Session.objects.select_related("team", "quarter", "facilitator"), pk=pk)
    keys = session.step_keys
    step = request.GET.get("s")
    is_facilitator = session.facilitator_id == request.user.pk
    if step in keys:
        if is_facilitator and step != session.current_step and not session.is_concluded:
            session.current_step = step
            session.save(update_fields=["current_step"])
    else:
        step = session.current_step if session.current_step in keys else keys[0]
    request._team = session.team
    request._quarter = session.quarter
    idx = keys.index(step)
    counts = dict(session.items.values_list("step").annotate(n=Count("id")))
    agenda = [(k, label, counts.get(k, 0)) for k, label, _ in session.agenda]
    ctx = {
        "s": session, "step": step, "step_label": session.agenda[idx][1], "step_hint": session.agenda[idx][2],
        "step_n": idx + 1, "agenda": agenda, "progress": round(100 * (idx + 1) / len(keys)),
        "prev": keys[idx - 1] if idx > 0 else None, "next_s": keys[idx + 1] if idx < len(keys) - 1 else None,
        "is_facilitator": is_facilitator, "can_run": can_run(request.user, session),
        "attendees": list(session.attendees.order_by("name")), "hide_scope": True,
    }
    ctx.update(step_context(request, session, step))
    return render(request, "planning/session.html", ctx)


@require_POST
def session_update(request, pk):
    session = get_object_or_404(Session, pk=pk)
    require(can_run(request.user, session))
    fields = []
    if "notes" in request.POST:
        session.notes = request.POST["notes"]
        fields.append("notes")
    if request.POST.get("facilitate"):
        session.facilitator = request.user
        fields.append("facilitator")
    if fields:
        session.save(update_fields=fields)
    if "attendees_present" in request.POST:
        session.attendees.set(request.POST.getlist("attendees"))
        return changed()
    if "facilitate" in request.POST:
        return changed("You're facilitating.")
    return HttpResponse(status=204)


@require_POST
def item_add(request, pk):
    session = get_object_or_404(Session, pk=pk)
    require(can_run(request.user, session))
    text = request.POST.get("text", "").strip()
    step, kind = request.POST.get("step", ""), request.POST.get("kind", "")
    if not text or step not in session.step_keys or kind not in {k for k, _, _ in STEP_ITEMS.get(step, [])}:
        return changed("Write something first.", "error") if is_htmx(request) else redirect("session", pk=pk)
    SessionItem.objects.create(session=session, step=step, kind=kind, text=text, author=request.user, sort=session.items.filter(step=step).count())
    return changed() if is_htmx(request) else redirect(f"/sessions/{pk}/?s={step}")


@require_POST
def item_action(request, pk):
    item = get_object_or_404(SessionItem.objects.select_related("session__team", "session__quarter"), pk=pk)
    session = item.session
    require(can_run(request.user, session))
    action = request.POST.get("action")
    team = session.team
    if action == "delete":
        item.delete()
        return changed()
    if action == "issue":
        Issue.objects.create(team=team, title=item.text[:200], owner=request.user, horizon=Issue.LONG, created_by=request.user)
        item.rag = "issue"
        item.save(update_fields=["rag"])
        return changed("Added to the long-term Issues List.")
    if action == "rock" and session.quarter:
        owner = User.objects.filter(pk=request.POST.get("owner") or 0).first() or request.user
        goal = Goal.objects.filter(pk=request.POST.get("goal") or 0).first()
        Rock.objects.create(
            team=team, quarter=session.quarter, is_company=team.is_leadership, title=item.text[:200], owner=owner, goal=goal,
            sort=Rock.objects.filter(team=team, quarter=session.quarter).count(),
        )
        item.rag = "rock"
        item.save(update_fields=["rag"])
        return changed(f"Rock set for {session.quarter.name}.")
    if action == "goal":
        Goal.objects.create(title=item.text[:240], owner=request.user, sort=Goal.objects.count())
        item.rag = "goal"
        item.save(update_fields=["rag"])
        return changed("Added to the 1-year goals.")
    return HttpResponse(status=400)


@require_POST
def rock_add(request, pk):
    session = get_object_or_404(Session.objects.select_related("team", "quarter"), pk=pk)
    require(can_run(request.user, session) and session.quarter)
    title = request.POST.get("title", "").strip()
    if not title:
        return changed("A rock needs a title.", "error")
    owner = User.objects.filter(pk=request.POST.get("owner") or 0).first() or request.user
    goal = Goal.objects.filter(pk=request.POST.get("goal") or 0).first()
    Rock.objects.create(
        team=session.team, quarter=session.quarter, is_company=session.team.is_leadership, title=title[:200], owner=owner, goal=goal,
        sort=Rock.objects.filter(team=session.team, quarter=session.quarter).count(),
    )
    return changed(f"Rock set for {session.quarter.name}.")


@require_POST
def goal_add(request, pk):
    session = get_object_or_404(Session, pk=pk)
    require(can_run(request.user, session) and is_admin(request.user))
    title = request.POST.get("title", "").strip()
    if not title:
        return changed("A goal needs a title.", "error")
    owner = User.objects.filter(pk=request.POST.get("owner") or 0).first()
    Goal.objects.create(title=title[:240], owner=owner, strategy=request.POST.get("strategy", ""), sort=Goal.objects.count())
    return changed("Goal added to the V/TO.")


@require_POST
def session_rate(request, pk):
    session = get_object_or_404(Session, pk=pk)
    user_id = int(request.POST.get("user") or request.user.pk)
    require(user_id == request.user.pk or session.facilitator_id == request.user.pk or is_admin(request.user))
    raw = request.POST.get("rating", "")
    rating = int(raw) if raw.isdigit() and 1 <= int(raw) <= 10 else None
    SessionRating.objects.update_or_create(session=session, user_id=user_id, defaults={"rating": rating})
    return changed()


@require_POST
def session_conclude(request, pk):
    session = get_object_or_404(Session, pk=pk)
    require(can_run(request.user, session))
    if request.POST.get("reopen"):
        session.concluded_at = None
    else:
        session.concluded_at = timezone.now()
        session.current_step = "conclude"
        messages.success(request, "Session concluded. Great work.")
    session.save(update_fields=["concluded_at", "current_step"])
    return redirect(f"/sessions/{session.pk}/?s=conclude")
