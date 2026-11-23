import datetime as dt
import json

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import monday_of
from core.forms import DateInput, PersonField, StyledForm, people_choices
from core.permissions import can_edit_owned, is_admin, is_team_member
from core.utils import go_back, is_htmx, require, scope
from todos.views import TodoForm

from .models import Milestone, Rock, RockUpdate
from .services import record_update


class RockForm(StyledForm, forms.ModelForm):
    owner = PersonField(queryset=None, required=False)

    class Meta:
        model = Rock
        fields = ["title", "owner", "due_date", "status", "is_company", "description"]
        widgets = {"due_date": DateInput(), "description": forms.Textarea(attrs={"rows": 4})}

    full_width = ["title"]

    def __init__(self, *args, team=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        team = team or (self.instance.team if self.instance.team_id else None)
        self.fields["owner"].queryset = people_choices(team, include=[self.instance.owner_id])
        if team is not None and team.is_leadership and not self.instance.pk:
            self.fields["is_company"].initial = True
        if user is not None and not is_admin(user) and not (team and team.is_leadership):
            self.fields.pop("is_company")


def rock_summary(rocks):
    rocks = list(rocks)
    return {
        "total": len(rocks),
        "on_track": sum(r.status == Rock.ON_TRACK for r in rocks),
        "off_track": sum(r.status == Rock.OFF_TRACK for r in rocks),
        "done": sum(r.status == Rock.DONE for r in rocks),
    }


def with_strips(rocks, quarter=None):
    """Attach each rock's 13-week G/Y/R strip and this week's update (prefetch `updates` first)."""
    rocks = list(rocks)
    this_week = monday_of(timezone.localdate())
    for r in rocks:
        q = quarter if quarter is not None and quarter.pk == r.quarter_id else r.quarter
        r.strip = r.week_strip(q.weeks()) if q else []
        r.this_week = next((u for u in r.updates.all() if u.week_start == this_week), None)
    return rocks


def rocks_for(team, quarter):
    qs = Rock.objects.filter(quarter=quarter).select_related("owner", "team", "quarter").prefetch_related("milestones", "updates")
    company = with_strips(qs.filter(is_company=True), quarter)
    team_rocks = with_strips(qs.filter(team=team, is_company=False), quarter)
    return company, team_rocks


def can_reorder(user, team):
    return team is not None and (is_admin(user) or is_team_member(user, team))


def rocks_list(request):
    team, quarter = scope(request)
    company, team_rocks = rocks_for(team, quarter)
    can_add = is_admin(request.user) or is_team_member(request.user, team)
    return render(
        request,
        "rocks/rocks.html",
        {
            "company_rocks": company,
            "team_rocks": team_rocks,
            "summary": rock_summary(company + team_rocks),
            "can_add": can_add,
            "can_reorder": can_reorder(request.user, team),
            "company_sortable": bool(team and team.is_leadership and can_reorder(request.user, team)),
            "strip_weeks": quarter.weeks() if quarter else [],
            "form": RockForm(team=team, user=request.user, initial={"owner": request.user.pk}) if can_add else None,
            "statuses": Rock.STATUS_CHOICES,
        },
    )


@require_POST
def rock_new(request):
    team, quarter = scope(request)
    require(is_admin(request.user) or is_team_member(request.user, team))
    form = RockForm(request.POST, team=team, user=request.user)
    if form.is_valid():
        rock = form.save(commit=False)
        rock.team = team
        rock.quarter = quarter
        if team.is_leadership and "is_company" not in form.fields:
            rock.is_company = True
        rock.sort = Rock.objects.filter(quarter=quarter, team=team).count()
        rock.save()
        messages.success(request, f"Rock “{rock.title}” added.")
        return redirect("rock_detail", pk=rock.pk)
    messages.error(request, "A rock needs a title.")
    return go_back(request, "/rocks/")


@require_POST
def rock_status(request, pk):
    rock = get_object_or_404(Rock.objects.select_related("owner", "team"), pk=pk)
    require(can_edit_owned(request.user, rock))
    status = request.POST.get("status")
    this_week = rock.updates.filter(week_start=monday_of(timezone.localdate())).first()
    if status == Rock.OFF_TRACK and is_htmx(request) and not (this_week and this_week.color == RockUpdate.RED):
        # Off track needs a recovery plan: open the weekly update panel preset to red instead.
        resp = render(request, "rocks/_update_panel.html", update_panel_ctx(rock, request, color=RockUpdate.RED))
        resp["HX-Retarget"] = "#panel-body"
        resp["HX-Reswap"] = "innerHTML"
        resp["HX-Trigger-After-Swap"] = json.dumps({"panel:open": True, "rock:changed": {"id": rock.pk}})
        return resp
    if status in dict(Rock.STATUS_CHOICES):
        rock.status = status
        rock.save(update_fields=["status", "updated_at"])
    if is_htmx(request) and request.POST.get("partial"):
        return render_row(request, rock, request.POST)
    return go_back(request, "/rocks/")


def render_row(request, rock, params):
    rock = Rock.objects.select_related("owner", "team", "quarter").prefetch_related("milestones", "updates").get(pk=rock.pk)
    with_strips([rock])
    return render(request, "rocks/_rock.html", {
        "r": rock, "statuses": Rock.STATUS_CHOICES, "mode": params.get("mode", ""), "meeting_id": params.get("meeting", ""),
    })


def rock_row(request, pk):
    return render_row(request, get_object_or_404(Rock, pk=pk), request.GET)


def update_panel_ctx(rock, request, color="", form=None, error=""):
    weeks = [w for w in (rock.quarter.weeks() if rock.quarter_id else []) if w <= monday_of(timezone.localdate())] or [monday_of(timezone.localdate())]
    week = monday_of(timezone.localdate())
    existing = rock.updates.filter(week_start=week).first()
    data = form or {
        "color": color or (existing.color if existing else ""),
        "note": existing.note if existing else "",
        "recovery_plan": existing.recovery_plan if existing else "",
        "week": week.isoformat(),
    }
    return {
        "rock": rock, "data": data, "error": error, "weeks": list(reversed(weeks)),
        "colors": RockUpdate.COLOR_CHOICES, "recent": rock.updates.select_related("author")[:4],
        "reload": request.GET.get("reload") or request.POST.get("reload") or "",
    }


def rock_update(request, pk):
    """Weekly G/Y/R check-in in the side panel. Red requires a recovery plan."""
    rock = get_object_or_404(Rock.objects.select_related("owner", "team", "quarter"), pk=pk)
    require(can_edit_owned(request.user, rock))
    if request.method == "POST":
        data = {k: request.POST.get(k, "") for k in ("color", "note", "recovery_plan", "week")}
        try:
            week = dt.date.fromisoformat(data["week"]) if data["week"] else None
        except ValueError:
            week = None
        try:
            record_update(rock, request.user, data["color"], data["note"], data["recovery_plan"], week=week)
        except ValidationError as e:
            resp = render(request, "rocks/_update_panel.html", update_panel_ctx(rock, request, form=data, error=" ".join(e.messages)))
            resp.status_code = 422
            return resp
        if not is_htmx(request):
            messages.success(request, "Rock update saved.")
            return go_back(request, f"/rocks/{rock.pk}/")
        resp = HttpResponse(status=204)
        if request.POST.get("reload"):
            resp["HX-Refresh"] = "true"
        else:
            resp["HX-Trigger"] = json.dumps({"panel:close": True, "rock:changed": {"id": rock.pk}})
        return resp
    return render(request, "rocks/_update_panel.html", update_panel_ctx(rock, request))


@require_POST
def rocks_sort(request):
    team, quarter = scope(request)
    require(can_reorder(request.user, team))
    ids = [int(x) for x in request.POST.get("ids", "").split(",") if x.strip().isdigit()]
    rocks = {r.pk: r for r in Rock.objects.filter(pk__in=ids, quarter=quarter)}
    for i, pk in enumerate(ids):
        r = rocks.get(pk)
        if r and (r.team_id == team.pk or r.is_company):
            Rock.objects.filter(pk=pk).update(sort=i)
    return HttpResponse(status=204)


def rock_detail(request, pk):
    rock = get_object_or_404(Rock.objects.select_related("owner", "team", "quarter"), pk=pk)
    editable = can_edit_owned(request.user, rock)
    form = RockForm(request.POST or None, instance=rock, user=request.user)
    if request.method == "POST":
        require(editable)
        if "delete" in request.POST:
            require(is_admin(request.user) or rock.owner_id == request.user.pk)
            rock.delete()
            messages.success(request, "Rock deleted.")
            return redirect("rocks")
        if form.is_valid():
            form.save()
            messages.success(request, "Rock saved.")
            return redirect("rock_detail", pk=rock.pk)
    return render(
        request,
        "rocks/rock_detail.html",
        {
            "rock": rock,
            "form": form,
            "editable": editable,
            "milestones": rock.milestones.all(),
            "todos": rock.todos.select_related("owner"),
            "issues": rock.issues.select_related("owner"),
            "todo_form": TodoForm(team=rock.team, user=request.user),
            "updates": rock.updates.select_related("author"),
            "strip": rock.week_strip(rock.quarter.weeks()) if rock.quarter_id else [],
            "statuses": Rock.STATUS_CHOICES,
            "rock_todo_url": reverse("rock_todo", args=[rock.pk]),
            "today": timezone.localdate(),
        },
    )


@require_POST
def milestone_add(request, pk):
    rock = get_object_or_404(Rock, pk=pk)
    require(can_edit_owned(request.user, rock))
    title = request.POST.get("title", "").strip()
    if title:
        Milestone.objects.create(
            rock=rock, title=title[:200], due_date=request.POST.get("due_date") or None, sort=rock.milestones.count()
        )
    return go_back(request, f"/rocks/{rock.pk}/")


@require_POST
def milestone_toggle(request, pk):
    ms = get_object_or_404(Milestone.objects.select_related("rock"), pk=pk)
    require(can_edit_owned(request.user, ms.rock))
    if "delete" in request.POST:
        ms.delete()
    else:
        ms.done = request.POST.get("done") in {"1", "on", "true"}
        ms.save(update_fields=["done"])
    return go_back(request, f"/rocks/{ms.rock_id}/")


@require_POST
def rock_todo(request, pk):
    from todos.views import create_todo, send_if_asked

    rock = get_object_or_404(Rock, pk=pk)
    require(can_edit_owned(request.user, rock) or is_team_member(request.user, rock.team))
    send_if_asked(request, create_todo(request.user, rock.team, request.POST, rock=rock))
    return go_back(request, f"/rocks/{rock.pk}/")
