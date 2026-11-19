import datetime as dt
import json

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.charts import GREEN, RED, YELLOW, donut
from core.forms import DateInput, PersonField, StyledForm, people_choices
from core.models import User, monday_of
from core.permissions import can_edit_owned, is_admin, is_team_member
from core.utils import go_back, is_htmx, require, scope
from todos.views import TodoForm
from vision.models import Goal

from .models import RAG_CHOICES, Milestone, Rock, RockUpdate


class RockForm(StyledForm, forms.ModelForm):
    owner = PersonField(queryset=None, required=False)

    class Meta:
        model = Rock
        fields = ["title", "owner", "due_date", "status", "is_company", "goal", "description"]
        widgets = {"due_date": DateInput(), "description": forms.Textarea(attrs={"rows": 4})}

    full_width = ["title"]

    def __init__(self, *args, team=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        team = team or (self.instance.team if self.instance.team_id else None)
        self.fields["owner"].queryset = people_choices(team, include=[self.instance.owner_id])
        self.fields["goal"].queryset = Goal.objects.filter(done=False) | Goal.objects.filter(pk=self.instance.goal_id or 0)
        self.fields["goal"].empty_label = "— Not tied to a 1-year goal —"
        self.fields["status"].required = False
        if team is not None and team.is_leadership and not self.instance.pk:
            self.fields["is_company"].initial = True
        if user is not None and not is_admin(user) and not (team and team.is_leadership):
            self.fields.pop("is_company")

    def clean_status(self):
        return self.cleaned_data.get("status") or self.instance.status or Rock.ON_TRACK


def rock_summary(rocks):
    rocks = list(rocks)
    rags = [r.rag for r in rocks]
    return {
        "total": len(rocks),
        "on_track": sum(r.status == Rock.ON_TRACK for r in rocks),
        "off_track": sum(r.status == Rock.OFF_TRACK for r in rocks),
        "done": sum(r.status == Rock.DONE for r in rocks),
        "green": rags.count("green"),
        "yellow": rags.count("yellow"),
        "red": rags.count("red"),
        "updated": sum(1 for r in rocks if r.status != Rock.DONE and not r.needs_update_this_week()),
        "open": sum(1 for r in rocks if r.status != Rock.DONE),
    }


def summary_donut(s):
    segs = [(s["green"], GREEN, "Green"), (s["yellow"], YELLOW, "Yellow"), (s["red"], RED, "Red"), (s["done"], "#0a0a0a", "Done")]
    return donut(segs, size=84, center=str(s["total"]), sub="rocks")


def rocks_for(team, quarter):
    qs = (
        Rock.objects.filter(quarter=quarter)
        .select_related("owner", "team", "quarter", "goal")
        .prefetch_related("milestones", "updates")
    )
    company = qs.filter(is_company=True)
    team_rocks = qs.filter(team=team, is_company=False)
    return company, team_rocks


def rocks_list(request):
    team, quarter = scope(request)
    company, team_rocks = rocks_for(team, quarter)
    mine = request.GET.get("owner") == "me"
    if mine:
        company, team_rocks = company.filter(owner=request.user), team_rocks.filter(owner=request.user)
    company, team_rocks = list(company), list(team_rocks)
    can_add = is_admin(request.user) or is_team_member(request.user, team)
    summary = rock_summary(company + team_rocks)
    milestones = [m for r in company + team_rocks for m in r.milestones.all()]
    return render(
        request,
        "rocks/rocks.html",
        {
            "company_rocks": company,
            "team_rocks": team_rocks,
            "summary": summary,
            "donut": summary_donut(summary),
            "milestones_done": sum(1 for m in milestones if m.done),
            "milestones_total": len(milestones),
            "due_mine": [r for r in company + team_rocks if r.owner_id == request.user.pk and r.needs_update_this_week()],
            "mine": mine,
            "can_add": can_add,
            "can_reorder": can_add and not mine,
            "company_reorder": can_add and not mine and (team.is_leadership or is_admin(request.user)),
            "statuses": Rock.STATUS_CHOICES,
            "this_monday": monday_of(timezone.localdate()),
        },
    )


def _trigger(response, message=None, close=False, **extra):
    events = {"rocksChanged": True, **extra}
    if message:
        events["toast"] = {"value": message}
    if close:
        events["closePanel"] = True
    response["HX-Trigger"] = json.dumps(events)
    return response


def rock_new(request):
    team, quarter = scope(request)
    require(is_admin(request.user) or is_team_member(request.user, team))
    if request.method != "POST":
        form = RockForm(team=team, user=request.user, initial={"owner": request.user.pk})
        return render(request, "rocks/_new_panel.html", {"form": form})
    form = RockForm(request.POST, team=team, user=request.user)
    if form.is_valid():
        rock = form.save(commit=False)
        rock.team = team
        rock.quarter = quarter
        if team.is_leadership and "is_company" not in form.fields:
            rock.is_company = True
        rock.sort = Rock.objects.filter(quarter=quarter, team=team).count()
        rock.save()
        if is_htmx(request):
            return _trigger(HttpResponse(""), f"Rock “{rock.title}” added.", close=True)
        messages.success(request, f"Rock “{rock.title}” added.")
        return redirect("rock_detail", pk=rock.pk)
    if is_htmx(request):
        return render(request, "rocks/_new_panel.html", {"form": form})
    messages.error(request, "A rock needs a title.")
    return go_back(request, "/rocks/")


@require_POST
def rock_status(request, pk):
    rock = get_object_or_404(Rock.objects.select_related("owner", "team"), pk=pk)
    require(can_edit_owned(request.user, rock))
    status = request.POST.get("status")
    if status in dict(Rock.STATUS_CHOICES):
        rock.status = status
        rock.save(update_fields=["status", "updated_at"])
    if is_htmx(request) and request.POST.get("partial"):
        return render(request, "rocks/_rock.html", {"r": rock, "statuses": Rock.STATUS_CHOICES, "mode": request.POST.get("mode", ""), "meeting_id": request.POST.get("meeting", "")})
    return go_back(request, "/rocks/")


def _update_week(raw):
    try:
        return monday_of(dt.date.fromisoformat(raw))
    except (TypeError, ValueError):
        return monday_of(timezone.localdate())


def rock_update(request, pk):
    """The owner's weekly G/Y/R call. Red needs a recovery plan."""
    rock = get_object_or_404(Rock.objects.select_related("owner", "team", "quarter"), pk=pk)
    require(can_edit_owned(request.user, rock))
    week = _update_week(request.POST.get("week") or request.GET.get("week"))
    existing = rock.updates.filter(week_start=week).first()
    error = ""
    if request.method == "POST":
        rag = request.POST.get("rag", "")
        note = request.POST.get("note", "").strip()
        plan = request.POST.get("recovery_plan", "").strip()
        if rag not in dict(RAG_CHOICES):
            error = "Pick green, yellow or red."
        elif rag == "red" and not plan:
            error = "A red rock needs a recovery plan: what will you do to get it back on track?"
        else:
            RockUpdate.objects.update_or_create(
                rock=rock, week_start=week, defaults={"rag": rag, "note": note, "recovery_plan": plan if rag == "red" else "", "author": request.user}
            )
            msg = f"{rock.title}: {dict(RAG_CHOICES)[rag]} for the week of {week:%b %-d}."
            if is_htmx(request):
                return _trigger(HttpResponse(""), msg, close=True)
            messages.success(request, msg)
            return go_back(request, f"/rocks/{rock.pk}/")
        existing = RockUpdate(rock=rock, week_start=week, rag=rag, note=note, recovery_plan=plan)
    weeks = [w for w in rock.quarter.weeks() if w <= monday_of(timezone.localdate())] or rock.quarter.weeks()[:1]
    resp = render(request, "rocks/_update_panel.html", {
        "rock": rock, "week": week, "weeks": weeks, "u": existing, "error": error,
        "previous": rock.updates.exclude(week_start=week).first(), "rags": RAG_CHOICES,
    })
    if error:
        resp.status_code = 200
    return resp


def rock_detail(request, pk):
    rock = get_object_or_404(Rock.objects.select_related("owner", "team", "quarter", "goal"), pk=pk)
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
            if is_htmx(request):
                # Text edits save quietly; changes that alter the header re-render the page.
                if set(form.changed_data) & {"status", "owner", "goal", "is_company", "due_date"}:
                    return _trigger(HttpResponse(status=204))
                return HttpResponse(status=204)
            messages.success(request, "Rock saved.")
            return redirect("rock_detail", pk=rock.pk)
        if is_htmx(request):
            resp = HttpResponse(status=422)
            resp["HX-Trigger"] = json.dumps({"toast": {"value": "A rock needs a title.", "kind": "error"}})
            return resp
    return render(
        request,
        "rocks/rock_detail.html",
        {
            "rock": rock,
            "form": form,
            "editable": editable,
            "milestones": rock.milestones.select_related("owner"),
            "updates": rock.updates.select_related("author"),
            "todos": rock.todos.select_related("owner"),
            "issues": rock.issues.select_related("owner"),
            "todo_form": TodoForm(team=rock.team, user=request.user),
            "statuses": Rock.STATUS_CHOICES,
            "rock_todo_url": reverse("rock_todo", args=[rock.pk]),
            "today": timezone.localdate(),
            "people": people_choices(rock.team, include=[rock.owner_id]),
            "hide_scope": True,
        },
    )


@require_POST
def rocks_reorder(request):
    team, quarter = scope(request)
    require(is_admin(request.user) or is_team_member(request.user, team))
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    by_id = {r.pk: r for r in Rock.objects.filter(quarter=quarter, pk__in=ids)}
    for sort, pk in enumerate(ids):
        r = by_id.get(pk)
        if r and (is_admin(request.user) or r.team_id == team.pk) and r.sort != sort:
            r.sort = sort
            r.save(update_fields=["sort"])
    return HttpResponse(status=204)


def _milestones_partial(request, rock):
    return render(request, "rocks/_milestones.html", {
        "rock": rock, "milestones": rock.milestones.select_related("owner"), "editable": can_edit_owned(request.user, rock),
        "today": timezone.localdate(), "people": people_choices(rock.team, include=[rock.owner_id]),
    })


@require_POST
def milestone_add(request, pk):
    rock = get_object_or_404(Rock, pk=pk)
    require(can_edit_owned(request.user, rock))
    title = request.POST.get("title", "").strip()
    if title:
        owner = User.objects.filter(pk=request.POST.get("owner") or 0).first() or rock.owner
        Milestone.objects.create(
            rock=rock, title=title[:200], owner=owner, due_date=request.POST.get("due_date") or None, sort=rock.milestones.count()
        )
    if is_htmx(request):
        return _milestones_partial(request, rock)
    return go_back(request, f"/rocks/{rock.pk}/")


@require_POST
def milestone_toggle(request, pk):
    ms = get_object_or_404(Milestone.objects.select_related("rock"), pk=pk)
    require(can_edit_owned(request.user, ms.rock))
    if "delete" in request.POST:
        ms.delete()
    else:
        ms.set_done(request.POST.get("done") in {"1", "on", "true"})
    if is_htmx(request):
        return _milestones_partial(request, ms.rock)
    return go_back(request, f"/rocks/{ms.rock_id}/")


@require_POST
def milestone_reorder(request, pk):
    rock = get_object_or_404(Rock, pk=pk)
    require(can_edit_owned(request.user, rock))
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    by_id = {m.pk: m for m in rock.milestones.filter(pk__in=ids)}
    for sort, mid in enumerate(ids):
        if mid in by_id:
            by_id[mid].sort = sort
            by_id[mid].save(update_fields=["sort"])
    return HttpResponse(status=204)


@require_POST
def rock_todo(request, pk):
    from todos.views import create_todo

    rock = get_object_or_404(Rock, pk=pk)
    require(can_edit_owned(request.user, rock) or is_team_member(request.user, rock.team))
    create_todo(request.user, rock.team, request.POST, rock=rock)
    return go_back(request, f"/rocks/{rock.pk}/")
