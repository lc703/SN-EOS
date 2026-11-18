from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import DateInput, PersonField, StyledForm, people_choices
from core.permissions import can_edit_owned, is_admin, is_team_member
from core.utils import go_back, is_htmx, require, scope
from todos.views import TodoForm

from .models import Milestone, Rock


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


def rocks_for(team, quarter):
    qs = Rock.objects.filter(quarter=quarter).select_related("owner", "team").prefetch_related("milestones")
    company = qs.filter(is_company=True)
    team_rocks = qs.filter(team=team, is_company=False)
    return company, team_rocks


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
            "summary": rock_summary(list(company) + list(team_rocks)),
            "can_add": can_add,
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
    if status in dict(Rock.STATUS_CHOICES):
        rock.status = status
        rock.save(update_fields=["status", "updated_at"])
    if is_htmx(request) and request.POST.get("partial"):
        return render(request, "rocks/_rock.html", {"r": rock, "statuses": Rock.STATUS_CHOICES, "mode": request.POST.get("mode", ""), "meeting_id": request.POST.get("meeting", "")})
    return go_back(request, "/rocks/")


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
            "history": (rock.legacy or {}).get("status_history", []),
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
    from todos.views import create_todo

    rock = get_object_or_404(Rock, pk=pk)
    require(can_edit_owned(request.user, rock) or is_team_member(request.user, rock.team))
    create_todo(request.user, rock.team, request.POST, rock=rock)
    return go_back(request, f"/rocks/{rock.pk}/")
