import datetime as dt

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe

from core.forms import people_choices
from core.models import monday_of
from core.scoping import for_team
from core.permissions import is_admin, is_team_member
from core.utils import go_back, is_htmx, require, scope
from issues.models import Issue
from rocks.models import Rock
from rocks.views import rock_summary, with_strips
from scorecard.plants import scorecard_for_team
from scorecard.views import build_rows
from todos.models import Todo, default_due, weekly_completion
from todos.views import TodoForm

from .models import SECTION_KEYS, SECTIONS, Headline, Meeting, MeetingRating


def can_run(user, meeting):
    return is_admin(user) or is_team_member(user, meeting.team)


def meetings_list(request):
    team, _ = scope(request)
    meetings = for_team(Meeting.objects.all(), team).select_related("team", "facilitator").prefetch_related("ratings", "attendees")[:30]
    return render(
        request,
        "meetings/meetings.html",
        {"meetings": meetings, "can_run": is_admin(request.user) or is_team_member(request.user, team)},
    )


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
    quarter = meeting.quarter
    if not quarter:
        return [monday_of(meeting.date) - dt.timedelta(weeks=i) for i in range(5, -1, -1)]
    weeks = [w for w in quarter.weeks() if w <= monday_of(meeting.date)]
    return weeks[-6:] or quarter.weeks()[:6]


def section_context(request, meeting, section):
    team = meeting.team
    ctx = {}
    if section == "segue":
        ctx["members"] = people_choices(team, include=list(meeting.attendees.values_list("pk", flat=True)))
        ctx["attendee_ids"] = set(meeting.attendees.values_list("pk", flat=True))
    elif section == "scorecard":
        weeks = _scorecard_weeks(meeting)
        measurables, plant = scorecard_for_team(team)
        rows = build_rows(measurables, weeks, request.user, grouped=True, plant=plant)
        ctx.update(
            rows=rows, plant=plant, weeks=weeks, cols=",".join(w.isoformat() for w in weeks),
            show_trailing=True, show_trend=True,
            off_count=sum(1 for r in rows if r.is_red),
        )
    elif section == "rocks":
        qs = Rock.objects.filter(quarter=meeting.quarter).select_related("owner", "team", "quarter").prefetch_related("milestones", "updates")
        rocks = with_strips(qs if team.is_leadership else qs.filter(team=team), meeting.quarter)
        ctx.update(rocks=rocks, summary=rock_summary(rocks), statuses=Rock.STATUS_CHOICES)
    elif section == "headlines":
        since = meeting.started_at - dt.timedelta(days=7)
        ctx["headlines"] = for_team(Headline.objects.all(), team).select_related("team").filter(
            Q(meeting=meeting) | Q(meeting__isnull=True, created_at__gte=since)
        ).select_related("author")
    elif section == "todos":
        week_ago = meeting.date - dt.timedelta(days=7)
        todos = for_team(Todo.objects.filter(is_private=False), team).filter(
            Q(done=False) | Q(done_at__date__gte=week_ago)
        ).exclude(meeting=meeting).select_related("owner", "rock", "issue", "team")
        due = [t for t in todos if t.due_date <= meeting.date]
        ctx.update(
            todos=todos,
            due_pct=round(100 * sum(t.done for t in due) / len(due)) if due else None,
            due_done=sum(t.done for t in due), due_total=len(due),
            weekly=weekly_completion(for_team(Todo.objects.filter(is_private=False), team), weeks=4, today=meeting.date),
            form=TodoForm(team=team, user=request.user),
        )
    elif section == "ids":
        ctx.update(
            issues=for_team(Issue.objects.filter(horizon=Issue.SHORT, status=Issue.OPEN), team).select_related("owner", "team").prefetch_related("todos"),
            long_count=for_team(Issue.objects.filter(horizon=Issue.LONG, status=Issue.OPEN), team).count(),
            solved_here=meeting.solved_issues.all(),
            people=people_choices(team, include=[request.user.pk]),
            default_due=default_due(),
            horizon=Issue.SHORT,
            can_edit=True,
        )
    elif section == "conclude":
        ctx.update(conclude_context(meeting))
    ctx["rollup"] = bool(team.is_leadership)
    return ctx


def conclude_context(meeting):
    ratings = {r.user_id: r.rating for r in meeting.ratings.all()}
    attendees = list(meeting.attendees.order_by("name"))
    return {
        "new_todos": meeting.new_todos.select_related("owner", "issue"),
        "solved": meeting.solved_issues.select_related("owner").prefetch_related("todos"),
        "raised": meeting.raised_issues.filter(status=Issue.OPEN).select_related("owner"),
        "attendee_ratings": [(u, ratings.get(u.pk)) for u in attendees],
        "average": meeting.average_rating,
        "rating_range": range(1, 11),
        "headlines": meeting.headlines.select_related("author"),
    }


@require_safe
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
    for name in ("segue_notes", "notes", "cascading_messages"):
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
    if is_htmx(request) and request.POST.get("autosave"):
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


def recap(request, pk):
    meeting = get_object_or_404(Meeting.objects.select_related("team", "facilitator"), pk=pk)
    ctx = {"meeting": meeting, "hide_scope": True, **conclude_context(meeting)}
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
