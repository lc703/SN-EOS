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

from issues.models import Issue
from meetings.models import Meeting
from rocks.models import Rock
from rocks.views import rock_summary, summary_donut
from scorecard.models import Measurable
from scorecard.views import build_rows, week_summary
from todos.models import Todo, weekly_completion

from .charts import bars, sparkline

from .adapters import email_allowed
from .models import Quarter, User, monday_of
from .utils import scope

EXPORT_APPS = ["core", "scorecard", "rocks", "issues", "todos", "meetings", "vision", "people"]


def home(request):
    team, quarter = scope(request)
    user = request.user
    today = timezone.localdate()
    this_monday = monday_of(today)
    todos = list(Todo.objects.filter(owner=user, done=False).select_related("team", "rock", "issue").order_by("due_date"))
    rocks = (
        list(Rock.objects.filter(owner=user, quarter=quarter).select_related("team", "goal").prefetch_related("milestones", "updates"))
        if quarter else []
    )
    issues = Issue.objects.filter(owner=user, status=Issue.OPEN).select_related("team")
    measurables = user.measurables.filter(active=True).select_related("team", "owner")
    weeks = [w for w in quarter.weeks() if w <= this_monday][-6:] if quarter else []
    rows = build_rows(measurables, weeks, user)
    completion = weekly_completion(Todo.objects.filter(owner=user), weeks=6, today=today)
    my_teams = user.teams.all()
    open_meetings = Meeting.objects.filter(
        team__in=my_teams, concluded_at__isnull=True, date__gte=today - dt.timedelta(days=1)
    ).select_related("team")[:3]

    # Team pulse for the team in the scope bar.
    team_rocks = []
    if quarter:
        qs = Rock.objects.filter(quarter=quarter).prefetch_related("updates")
        team_rocks = list(qs.filter(is_company=True) if team.is_leadership else qs.filter(team=team))
    rsum = rock_summary(team_rocks)
    team_weeks = [w for w in quarter.weeks() if w < this_monday][-8:] if quarter else []
    team_rows = build_rows(Measurable.objects.filter(team=team, active=True).select_related("owner", "team"), team_weeks, user)
    sc = week_summary(team_rows, team_weeks)
    sc_last = next((s for s in reversed(sc) if s["scored"]), None)
    ratings = [m.average_rating for m in reversed(Meeting.objects.filter(team=team, concluded_at__isnull=False).prefetch_related("ratings")[:8])]
    ratings = [r for r in ratings if r]

    last_week = this_monday - dt.timedelta(weeks=1)
    missing = [r for r in build_rows(measurables, [last_week], user) if not r.cells[0].state] if quarter and quarter.contains(last_week) else []
    attention = {
        "updates": [r for r in rocks if r.status != Rock.DONE and r.needs_update_this_week()],
        "missing": missing,
        "overdue": [t for t in todos if t.due_date < today],
    }
    weeks_in = [w for w in quarter.weeks() if w <= this_monday] if quarter else []
    return render(request, "core/home.html", {
        "todos": todos,
        "rocks": rocks,
        "issues": issues,
        "rows": rows,
        "weeks": weeks,
        "completion": completion,
        "completion_bars": bars([(f"{w:%-m/%-d}", pct) for w, pct, _, _ in completion], goal=90, height=44, width=300)
        if any(pct is not None for _, pct, _, _ in completion) else "",
        "my_teams": my_teams,
        "open_meetings": open_meetings,
        "today": today,
        "statuses": Rock.STATUS_CHOICES,
        "attention": attention,
        "attention_count": sum(len(v) for v in attention.values()),
        "week_n": len(weeks_in),
        "quarter_pct": round(100 * len(weeks_in) / Quarter.WEEKS) if quarter else 0,
        "days_left": max((quarter.end_date - today).days, 0) if quarter else None,
        "rsum": rsum,
        "rock_donut": summary_donut(rsum),
        "sc_bars": bars([(f"{s['week']:%-m/%-d}", s["pct"]) for s in sc], goal=80, height=40, width=240),
        "sc_last": sc_last,
        "rating_spark": sparkline(ratings, goal=8, states=["green" if r >= 8 else "red" for r in ratings], width=150, height=40) if len(ratings) > 1 else "",
        "rating_last": ratings[-1] if ratings else None,
        "my_rock_pct": round(100 * sum(1 for r in rocks if r.rag in ("green", "done")) / len(rocks)) if rocks else None,
    })


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
