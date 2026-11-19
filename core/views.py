import datetime as dt
import json

from django.apps import apps
from django.conf import settings
from django.contrib.auth import authenticate, login
from django.core import serializers
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.safestring import mark_safe

from issues.models import Issue
from meetings.models import Meeting
from rocks.models import Rock
from rocks.views import rock_summary, with_strips
from scorecard.models import Measurable, ScoreEntry
from scorecard.views import build_rows
from todos.models import Todo, weekly_completion

from . import charts
from .adapters import email_allowed
from .models import User, monday_of
from .utils import scope

EXPORT_APPS = ["core", "scorecard", "rocks", "issues", "todos", "meetings", "vision", "people", "planning"]


def home(request):
    team, quarter = scope(request)
    user = request.user
    today = timezone.localdate()
    todos = Todo.objects.filter(owner=user, done=False).select_related("team", "rock", "issue").order_by("due_date")
    rocks = (
        with_strips(Rock.objects.filter(owner=user, quarter=quarter).select_related("team", "quarter").prefetch_related("milestones", "updates"), quarter)
        if quarter
        else []
    )
    issues = Issue.objects.filter(owner=user, status=Issue.OPEN).select_related("team")
    measurables = user.measurables.filter(active=True).select_related("team", "owner")
    weeks = []
    if quarter:
        this_monday = monday_of(today)
        weeks = [w for w in quarter.weeks() if w <= this_monday][-5:] or quarter.weeks()[:5]
    if quarter:
        weeks = [w for w in quarter.weeks() if w <= monday_of(today)][-8:] or quarter.weeks()[:8]
    rows = build_rows(measurables, weeks, user)
    completion = weekly_completion(Todo.objects.filter(owner=user), weeks=6, today=today)
    my_teams = user.teams.all()
    open_meetings = Meeting.objects.filter(
        team__in=my_teams, concluded_at__isnull=True, date__gte=today - dt.timedelta(days=1)
    ).select_related("team")[:3]
    summary = rock_summary(rocks)
    rock_chart = charts.donut(
        [(summary["done"], charts.INK), (summary["on_track"], charts.GREEN), (summary["off_track"], charts.RED)],
        size=104, thickness=13, label=f'{summary["done"] + summary["on_track"]}/{summary["total"]}' if summary["total"] else "—",
        sub="on track" if summary["total"] else "",
    )
    todo_chart = charts.bars(
        [w.strftime("%-m/%-d") for w, *_ in completion], [pct for _, pct, *_ in completion],
        width=300, height=96, goal=90, max_value=100, fmt=lambda v: f"{v:.0f}%",
    )
    return render(
        request,
        "core/home.html",
        {
            "rock_summary": summary,
            "rock_chart": mark_safe(rock_chart),
            "todo_chart": mark_safe(todo_chart),
            "pulse": team_pulse(team, quarter, today) if team and quarter else None,
            "todos": todos,
            "rocks": rocks,
            "issues": issues,
            "rows": rows,
            "weeks": weeks,
            "completion": completion,
            "my_teams": my_teams,
            "open_meetings": open_meetings,
            "today": today,
            "statuses": Rock.STATUS_CHOICES,
        },
    )


def team_pulse(team, quarter, today):
    """Leadership-at-a-glance numbers for the team in scope."""
    rocks = Rock.objects.filter(quarter=quarter)
    rocks = rocks.filter(is_company=True) if team.is_leadership else rocks.filter(team=team)
    rs = rock_summary(rocks)
    last_week = monday_of(today) - dt.timedelta(days=7)
    measurables = list(Measurable.objects.filter(team=team, active=True))
    entries = {e.measurable_id: e.value for e in ScoreEntry.objects.filter(measurable__in=measurables, week_start=last_week)}
    judged = [m.is_on_goal(entries.get(m.pk)) for m in measurables]
    judged = [j for j in judged if j is not None]
    team_completion = weekly_completion(Todo.objects.filter(team=team, is_private=False), weeks=1, today=today)
    last = team_completion[-1] if team_completion else None
    return {
        "team": team, "rocks": rs,
        "rocks_pct": round(100 * (rs["on_track"] + rs["done"]) / rs["total"]) if rs["total"] else None,
        "scorecard_pct": round(100 * sum(judged) / len(judged)) if judged else None,
        "scorecard_n": len(judged), "measurables": len(measurables), "week": last_week,
        "issues": Issue.objects.filter(team=team, status=Issue.OPEN).count(),
        "todo_pct": last[1] if last else None,
    }


def healthz(request):
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")


def export_json(request):
    if not request.user.is_admin:
        raise PermissionDenied
    data = []
    for label in EXPORT_APPS:
        for model in apps.get_app_config(label).get_models():
            rows = json.loads(serializers.serialize("json", model.objects.all()))
            for row in rows:
                row["fields"].pop("password", None)
            data.extend(rows)
    stamp = timezone.now().strftime("%Y%m%d-%H%M")
    resp = JsonResponse(data, safe=False, json_dumps_params={"indent": 1})
    resp["Content-Disposition"] = f'attachment; filename="sn-eos-{stamp}.json"'
    return resp


def dev_login(request):
    if not settings.DEV_LOGIN:
        raise Http404
    if request.method == "POST":
        user = get_object_or_404(User, pk=request.POST.get("user"), is_active=True)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect(request.POST.get("next") or "/")
    users = User.objects.filter(is_active=True).order_by("-role", "name")
    users = [u for u in users if u.can_sign_in] or list(users)
    return render(request, "account/dev_login.html", {"users": users, "next": request.GET.get("next", "/")})


@require_POST
def password_login(request):
    """Temporary staging sign-in. 404 unless STAGING_PASSWORD_LOGIN is on. No signup."""
    if not settings.STAGING_PASSWORD_LOGIN:
        raise Http404
    email = (request.POST.get("email") or "").strip().lower()
    password = request.POST.get("password") or ""
    nxt = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = "/"
    user = None
    if email_allowed(email) and password:
        user = authenticate(request, username=email, password=password)
    if user is None or not user.is_active or not email_allowed(user.email):
        ctx = {"password_error": "That email and password didn't work.", "email": email, "next": nxt}
        return render(request, "account/login.html", ctx, status=400)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect(nxt)
