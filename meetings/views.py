import datetime as dt

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.charts import line_chart
from core.forms import people_choices
from core.models import monday_of
from core.permissions import is_admin, is_team_member
from core.models import Team
from core.utils import go_back, hx_trigger, is_htmx, require, scope
from issues.models import Issue
from rocks.models import Rock
from rocks.views import rock_summary, summary_donut
from scorecard.models import Measurable
from scorecard.views import build_rows, week_summary
from todos.models import Todo, default_due, weekly_completion
from todos.views import TodoForm

from .models import SECTION_KEYS, SECTIONS, CascadingMessage, Headline, Meeting, MeetingRating

SECTION_HINTS = {
    "segue": "Everyone shares one personal and one professional best from the past week.",
    "scorecard": "Report the numbers: on or off. Anything red drops to the Issues list; don't solve it here.",
    "rocks": "Each owner calls their rock green, yellow or red. Red rocks drop to Issues.",
    "headlines": "Good and bad news about customers and employees, one sentence each. Anything that needs discussion drops to Issues.",
    "todos": "Last week's to-dos: done or not done. Check them off as owners report.",
    "ids": "Pick the top 3, then Identify, Discuss, Solve, one at a time. Solutions become to-dos.",
    "conclude": "Recap the to-dos, agree on cascading messages, and rate the meeting 1–10.",
}


def can_run(user, meeting):
    return is_admin(user) or is_team_member(user, meeting.team)


def meetings_list(request):
    team, _ = scope(request)
    meetings = list(Meeting.objects.filter(team=team).select_related("facilitator").prefetch_related("ratings", "attendees")[:30])
    rated = [m for m in reversed(meetings) if m.is_concluded and m.average_rating][-12:]
    points = [(f"{m.date:%b %-d}", m.average_rating, "green" if m.average_rating >= 8 else "red") for m in rated]
    chart = line_chart(points, goal=8, width=640, height=180, fmt=lambda v: f"{v:.1f}", title="Meeting rating") if len(points) > 1 else ""
    open_meeting = next((m for m in meetings if not m.is_concluded), None)
    scores = [m.average_rating for m in rated]
    return render(request, "meetings/meetings.html", {
        "meetings": meetings, "chart": chart, "open_meeting": open_meeting,
        "avg_rating": round(sum(scores) / len(scores), 1) if scores else None,
        "held": sum(1 for m in meetings if m.is_concluded), "rated_n": len(rated),
        "can_run": is_admin(request.user) or is_team_member(request.user, team),
    })


@require_POST
def meeting_start(request):
    team, quarter = scope(request)
    require(is_admin(request.user) or is_team_member(request.user, team))
    today = timezone.localdate()
    meeting = Meeting.objects.filter(team=team, date=today, concluded_at__isnull=True).first()
    if meeting is None:
        meeting = Meeting.objects.create(team=team, quarter=quarter, date=today, facilitator=request.user)
        meeting.attendees.set(team.members.filter(is_active=True))
    return redirect("meeting", pk=meeting.pk)


def _scorecard_weeks(meeting):
    # Early-week L10s report the week that just ended; later in the week, the current one.
    last = monday_of(meeting.date) - (dt.timedelta(weeks=1) if meeting.date.weekday() < 3 else dt.timedelta(0))
    return [last - dt.timedelta(weeks=i) for i in range(5, -1, -1)]


def section_context(request, meeting, section):
    team = meeting.team
    ctx = {}
    if section == "segue":
        ctx["members"] = people_choices(team, include=list(meeting.attendees.values_list("pk", flat=True)))
        ctx["attendee_ids"] = set(meeting.attendees.values_list("pk", flat=True))
    elif section == "scorecard":
        weeks = _scorecard_weeks(meeting)
        rows = build_rows(Measurable.objects.filter(team=team, active=True).select_related("owner", "team"), weeks, request.user)
        ctx.update(
            rows=rows, weeks=weeks, cols=",".join(w.isoformat() for w in weeks),
            show_trailing=True,
            summary=week_summary(rows, weeks),
            off_count=sum(1 for r in rows if r.is_red),
        )
    elif section == "rocks":
        rocks = list(meeting_rocks(meeting).select_related("goal").prefetch_related("updates"))
        summary = rock_summary(rocks)
        ctx.update(rocks=rocks, summary=summary, donut=summary_donut(summary), statuses=Rock.STATUS_CHOICES)
    elif section == "headlines":
        ctx["headlines"] = headlines_for(meeting)
        ctx["cascades_in"] = cascades_received(meeting)
    elif section == "todos":
        week_ago = meeting.date - dt.timedelta(days=7)
        todos = Todo.objects.filter(team=team, is_private=False).filter(
            Q(done=False) | Q(done_at__date__gte=week_ago)
        ).exclude(meeting=meeting).select_related("owner", "rock", "issue")
        due = [t for t in todos if t.due_date <= meeting.date]
        ctx.update(
            todos=todos,
            due_pct=round(100 * sum(t.done for t in due) / len(due)) if due else None,
            due_done=sum(t.done for t in due), due_total=len(due),
            weekly=weekly_completion(Todo.objects.filter(team=team, is_private=False), weeks=4, today=meeting.date),
            form=TodoForm(team=team, user=request.user),
        )
    elif section == "ids":
        ctx.update(
            issues=Issue.objects.filter(team=team, horizon=Issue.SHORT, status=Issue.OPEN).select_related("owner").prefetch_related("todos"),
            long_count=Issue.objects.filter(team=team, horizon=Issue.LONG, status=Issue.OPEN).count(),
            solved_here=meeting.solved_issues.all(),
            people=people_choices(team, include=[request.user.pk]),
            default_due=default_due(),
            horizon=Issue.SHORT,
            can_edit=True,
        )
    elif section == "conclude":
        ctx.update(conclude_context(meeting))
    return ctx


def meeting_rocks(meeting):
    qs = Rock.objects.filter(quarter=meeting.quarter).select_related("owner", "team").prefetch_related("milestones")
    return qs.filter(is_company=True) if meeting.team.is_leadership else qs.filter(team=meeting.team)


def headlines_for(meeting):
    since = meeting.started_at - dt.timedelta(days=7)
    return Headline.objects.filter(team=meeting.team).filter(
        Q(meeting=meeting) | Q(meeting__isnull=True, created_at__gte=since)
    ).select_related("author")


def cascades_received(meeting):
    """Messages other teams cascaded to this team since its previous L10 (or the last two weeks)."""
    prev = Meeting.objects.filter(team=meeting.team, started_at__lt=meeting.started_at).order_by("-started_at").first()
    since = prev.started_at if prev else meeting.started_at - dt.timedelta(days=14)
    return (
        CascadingMessage.objects.filter(Q(to_everyone=True) | Q(to_teams=meeting.team))
        .exclude(meeting__team=meeting.team)
        .filter(created_at__gte=since, created_at__lte=meeting.concluded_at or timezone.now())
        .select_related("meeting__team", "author")
        .distinct()
    )


def section_badges(meeting):
    team = meeting.team
    due_open = Todo.objects.filter(team=team, is_private=False, done=False, due_date__lte=meeting.date).exclude(meeting=meeting).count()
    return {
        "rocks": meeting_rocks(meeting).filter(status=Rock.OFF_TRACK).count(),
        "headlines": headlines_for(meeting).count() + cascades_received(meeting).count(),
        "todos": due_open,
        "ids": Issue.objects.filter(team=team, horizon=Issue.SHORT, status=Issue.OPEN).count(),
    }


def conclude_context(meeting):
    ratings = {r.user_id: r.rating for r in meeting.ratings.all()}
    attendees = list(meeting.attendees.order_by("name"))
    return {
        "cascades": meeting.cascades.prefetch_related("to_teams").select_related("author"),
        "cascade_teams": Team.objects.exclude(pk=meeting.team_id),
        "rated": sum(1 for v in ratings.values() if v),
        "new_todos": meeting.new_todos.select_related("owner", "issue"),
        "solved": meeting.solved_issues.select_related("owner").prefetch_related("todos"),
        "raised": meeting.raised_issues.filter(status=Issue.OPEN).select_related("owner"),
        "attendee_ratings": [(u, ratings.get(u.pk)) for u in attendees],
        "average": meeting.average_rating,
        "rating_range": range(1, 11),
    }


def meeting(request, pk):
    meeting = get_object_or_404(Meeting.objects.select_related("team", "quarter", "facilitator"), pk=pk)
    section = request.GET.get("s")
    is_facilitator = meeting.facilitator_id == request.user.pk
    if section in SECTION_KEYS:
        if is_facilitator and section != meeting.current_section and not meeting.is_concluded:
            meeting.current_section = section
            meeting.save(update_fields=["current_section"])
    else:
        section = meeting.current_section if meeting.current_section in SECTION_KEYS else "segue"
    request._team = meeting.team
    request._quarter = meeting.quarter
    idx = SECTION_KEYS.index(section)
    ctx = {
        "meeting": meeting,
        "section": section,
        "section_label": dict(SECTIONS)[section],
        "section_hint": SECTION_HINTS[section],
        "section_n": idx + 1,
        "progress": round(100 * (idx + 1) / len(SECTION_KEYS)),
        "badges": section_badges(meeting),
        "attendees": list(meeting.attendees.order_by("name")),
        "sections": SECTIONS,
        "prev": SECTION_KEYS[idx - 1] if idx > 0 else None,
        "next_s": SECTION_KEYS[idx + 1] if idx < len(SECTION_KEYS) - 1 else None,
        "is_facilitator": is_facilitator,
        "can_run": can_run(request.user, meeting),
        "meeting_id": meeting.pk,
        "mode": "meeting",
        "hide_scope": True,
        "wide": True,
    }
    ctx.update(section_context(request, meeting, section))
    return render(request, "meetings/meeting.html", ctx)


def meeting_where(request, pk):
    """Polled by attendees: shows a banner when the facilitator is on another section."""
    meeting = get_object_or_404(Meeting, pk=pk)
    here = request.GET.get("s")
    if meeting.is_concluded or meeting.facilitator_id == request.user.pk or meeting.current_section == here:
        return HttpResponse("")
    return render(request, "meetings/_where.html", {"meeting": meeting, "label": dict(SECTIONS).get(meeting.current_section)})


@require_POST
def meeting_update(request, pk):
    meeting = get_object_or_404(Meeting, pk=pk)
    require(can_run(request.user, meeting))
    fields = []
    for name in ("segue_notes", "notes"):
        if name in request.POST:
            setattr(meeting, name, request.POST[name])
            fields.append(name)
    if "attendees_present" in request.POST:
        meeting.attendees.set(request.POST.getlist("attendees"))
    if request.POST.get("facilitate"):
        meeting.facilitator = request.user
        fields.append("facilitator")
    if fields:
        meeting.save(update_fields=fields)
    if is_htmx(request):
        if "attendees_present" in request.POST or "facilitate" in request.POST:
            return hx_trigger(HttpResponse(status=204), meetingChanged=True)
        return HttpResponse(status=204)
    return go_back(request, f"/meetings/{meeting.pk}/")


@require_POST
def headline_add(request, pk):
    meeting = get_object_or_404(Meeting, pk=pk)
    require(can_run(request.user, meeting))
    text = request.POST.get("text", "").strip()
    if text:
        Headline.objects.create(
            team=meeting.team, meeting=meeting, kind=request.POST.get("kind") or Headline.CUSTOMER, text=text[:300], author=request.user
        )
    if is_htmx(request):
        return hx_trigger(HttpResponse(status=204), meetingChanged=True)
    return go_back(request, f"/meetings/{meeting.pk}/?s=headlines")


@require_POST
def rate(request, pk):
    meeting = get_object_or_404(Meeting, pk=pk)
    user_id = int(request.POST.get("user") or request.user.pk)
    # Each attendee rates themselves; the facilitator or an admin can enter ratings for the room.
    require(user_id == request.user.pk or meeting.facilitator_id == request.user.pk or is_admin(request.user))
    raw = request.POST.get("rating", "")
    rating = int(raw) if raw.isdigit() and 1 <= int(raw) <= 10 else None
    MeetingRating.objects.update_or_create(meeting=meeting, user_id=user_id, defaults={"rating": rating})
    if is_htmx(request):
        return hx_trigger(HttpResponse(status=204), meetingChanged=True)
    return go_back(request, f"/meetings/{meeting.pk}/?s=conclude")


@require_POST
def conclude(request, pk):
    meeting = get_object_or_404(Meeting, pk=pk)
    require(can_run(request.user, meeting))
    if request.POST.get("reopen"):
        meeting.concluded_at = None
    else:
        meeting.concluded_at = timezone.now()
        meeting.current_section = "conclude"
        messages.success(request, "Meeting concluded. Nice work.")
    meeting.save(update_fields=["concluded_at", "current_section"])
    return redirect(f"/meetings/{meeting.pk}/?s=conclude")


@require_POST
def cascade_add(request, pk):
    meeting = get_object_or_404(Meeting, pk=pk)
    require(can_run(request.user, meeting))
    text = request.POST.get("text", "").strip()
    everyone = request.POST.get("to_everyone") in {"1", "on", "true"}
    team_ids = [int(t) for t in request.POST.getlist("to_teams") if t.isdigit()]
    if not text or not (everyone or team_ids):
        msg = "Write the message and pick who it goes to."
        if is_htmx(request):
            return hx_trigger(HttpResponse(status=422), toast=msg, kind="error")
        messages.error(request, msg)
        return go_back(request, f"/meetings/{meeting.pk}/?s=conclude")
    c = CascadingMessage.objects.create(meeting=meeting, text=text, to_everyone=everyone, author=request.user)
    if not everyone:
        c.to_teams.set(Team.objects.filter(pk__in=team_ids).exclude(pk=meeting.team_id))
    if is_htmx(request):
        return hx_trigger(HttpResponse(status=204), toast="Cascading message added.", meetingChanged=True)
    return go_back(request, f"/meetings/{meeting.pk}/?s=conclude")


@require_POST
def cascade_delete(request, pk):
    c = get_object_or_404(CascadingMessage.objects.select_related("meeting"), pk=pk)
    require(can_run(request.user, c.meeting))
    meeting_pk = c.meeting_id
    c.delete()
    if is_htmx(request):
        return hx_trigger(HttpResponse(status=204), meetingChanged=True)
    return go_back(request, f"/meetings/{meeting_pk}/?s=conclude")


def recap(request, pk):
    meeting = get_object_or_404(Meeting.objects.select_related("team", "facilitator"), pk=pk)
    rocks = list(meeting_rocks(meeting).prefetch_related("updates")) if meeting.quarter_id else []
    ctx = {"meeting": meeting, "hide_scope": True, "rocks": rocks, "rock_summary": rock_summary(rocks),
           "cascades_in": cascades_received(meeting), **conclude_context(meeting)}
    return render(request, "meetings/recap.html", ctx)


@require_POST
def send_recap(request, pk):
    """Emails the recap text to attendees. Uses the console backend unless SMTP is configured."""
    meeting = get_object_or_404(Meeting.objects.select_related("team"), pk=pk)
    require(can_run(request.user, meeting))
    to = [u.email for u in meeting.attendees.all() if u.can_sign_in]
    body = render_to_string("meetings/recap_email.txt", {"meeting": meeting, "site_url": settings.SITE_URL, **conclude_context(meeting)})
    if to:
        send_mail(f"{meeting} recap", body, None, to, fail_silently=True)
        meeting.recap_sent_at = timezone.now()
        meeting.save(update_fields=["recap_sent_at"])
        messages.success(request, f"Recap sent to {len(to)} attendee(s).")
    else:
        messages.error(request, "No attendees with an email to send to.")
    return go_back(request, f"/meetings/{meeting.pk}/recap/")
