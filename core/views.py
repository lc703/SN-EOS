import datetime as dt
import json

from django.apps import apps
from django.conf import settings
from django.contrib.auth import login
from django.core import serializers
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from issues.models import Issue
from meetings.models import Meeting
from rocks.models import Rock
from scorecard.views import build_rows
from todos.models import Todo, weekly_completion

from .models import User, monday_of
from .utils import scope

EXPORT_APPS = ["core", "scorecard", "rocks", "issues", "todos", "meetings", "vision", "people"]


def home(request):
    team, quarter = scope(request)
    user = request.user
    today = timezone.localdate()
    todos = Todo.objects.filter(owner=user, done=False).select_related("team", "rock", "issue").order_by("due_date")
    rocks = (
        Rock.objects.filter(owner=user, quarter=quarter).select_related("team").prefetch_related("milestones")
        if quarter
        else Rock.objects.none()
    )
    issues = Issue.objects.filter(owner=user, status=Issue.OPEN).select_related("team")
    measurables = user.measurables.filter(active=True).select_related("team", "owner")
    weeks = []
    if quarter:
        this_monday = monday_of(today)
        weeks = [w for w in quarter.weeks() if w <= this_monday][-5:] or quarter.weeks()[:5]
    rows = build_rows(measurables, weeks, user)
    completion = weekly_completion(Todo.objects.filter(owner=user), weeks=4, today=today)
    my_teams = user.teams.all()
    open_meetings = Meeting.objects.filter(team__in=my_teams, concluded_at__isnull=True).select_related("team")[:3]
    return render(
        request,
        "core/home.html",
        {
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
