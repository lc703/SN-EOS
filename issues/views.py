import datetime as dt

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import PersonField, StyledForm, people_choices
from core.permissions import can_edit_team_item, is_admin, is_team_member
from core.utils import go_back, is_htmx, require, scope
from meetings.models import Headline, Meeting
from rocks.models import Rock
from scorecard.models import Measurable, ScoreEntry
from todos.models import default_due
from todos.views import TodoForm, create_todo

from .models import Issue


class IssueForm(StyledForm, forms.ModelForm):
    owner = PersonField(queryset=None, required=False)

    class Meta:
        model = Issue
        fields = ["title", "owner", "horizon", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    full_width = ["title"]

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        team = team or (self.instance.team if self.instance.team_id else None)
        self.fields["owner"].queryset = people_choices(team, include=[self.instance.owner_id])


def open_issues(team, horizon=Issue.SHORT):
    return Issue.objects.filter(team=team, horizon=horizon, status=Issue.OPEN).select_related("owner")


def issues_list(request):
    team, _ = scope(request)
    horizon = Issue.LONG if request.GET.get("list") == "long" else Issue.SHORT
    issues = open_issues(team, horizon).prefetch_related("todos")
    solved = Issue.objects.filter(team=team, status=Issue.SOLVED).select_related("owner").order_by("-solved_at", "-created_at")[:15]
    can_add = is_admin(request.user) or is_team_member(request.user, team)
    return render(
        request,
        "issues/issues.html",
        {
            "issues": issues,
            "solved": solved,
            "horizon": horizon,
            "counts": {
                h: Issue.objects.filter(team=team, horizon=h, status=Issue.OPEN).count() for h in (Issue.SHORT, Issue.LONG)
            },
            "can_add": can_add,
            "can_edit": can_add,
            "people": people_choices(team, include=[request.user.pk]),
            "default_due": default_due(),
        },
    )


@require_POST
def issue_new(request):
    team, _ = scope(request)
    require(is_admin(request.user) or is_team_member(request.user, team))
    form = IssueForm(request.POST, team=team)
    if form.is_valid():
        issue = form.save(commit=False)
        issue.team = team
        issue.created_by = request.user
        if not issue.owner_id:
            issue.owner = request.user
        issue.raised_meeting = Meeting.objects.filter(pk=request.POST.get("meeting") or 0).first()
        issue.save()
    else:
        messages.error(request, "An issue needs a title.")
    return go_back(request, "/issues/")


def issue_detail(request, pk):
    issue = get_object_or_404(Issue.objects.select_related("team", "owner", "source_measurable", "source_rock", "source_headline"), pk=pk)
    editable = can_edit_team_item(request.user, issue)
    form = IssueForm(request.POST or None, instance=issue)
    if request.method == "POST":
        require(editable)
        if "delete" in request.POST:
            issue.delete()
            messages.success(request, "Issue deleted.")
            return redirect("issues")
        if form.is_valid():
            form.save()
            messages.success(request, "Issue saved.")
            return redirect("issue_detail", pk=issue.pk)
    return render(
        request,
        "issues/issue_detail.html",
        {
            "issue": issue,
            "form": form,
            "editable": editable,
            "todos": issue.todos.select_related("owner"),
            "todo_form": TodoForm(team=issue.team, user=request.user),
            "people": people_choices(issue.team, include=[request.user.pk]),
            "default_due": default_due(),
            "meeting": Meeting.objects.filter(pk=request.GET.get("meeting") or 0).first(),
        },
    )


@require_POST
def issue_solve(request, pk):
    """IDS: optionally record the solution and create to-dos, then mark solved (or just add the to-dos)."""
    issue = get_object_or_404(Issue, pk=pk)
    require(can_edit_team_item(request.user, issue))
    meeting = Meeting.objects.filter(pk=request.POST.get("meeting") or 0).first()
    titles = request.POST.getlist("todo_title")
    owners = request.POST.getlist("todo_owner")
    dues = request.POST.getlist("todo_due")
    created = 0
    for i, title in enumerate(titles):
        todo = create_todo(
            request.user,
            issue.team,
            {
                "title": title,
                "owner": owners[i] if i < len(owners) else None,
                "due_date": (dues[i] if i < len(dues) else "") or None,
            },
            issue=issue,
            meeting=meeting,
        )
        created += bool(todo)
    resolution = request.POST.get("resolution", "").strip()
    if request.POST.get("action") == "solve":
        issue.solve(meeting=meeting, resolution=resolution)
        if not is_htmx(request):
            messages.success(request, f"Solved “{issue.title}”" + (f" with {created} to-do(s)." if created else "."))
    else:
        if resolution:
            issue.resolution = resolution
            issue.save(update_fields=["resolution"])
        if created and not is_htmx(request):
            messages.success(request, f"Added {created} to-do(s).")
    return go_back(request, f"/issues/{issue.pk}/")


@require_POST
def issue_reopen(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    require(can_edit_team_item(request.user, issue))
    issue.reopen()
    return go_back(request, f"/issues/{issue.pk}/")


@require_POST
def issue_priority(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    require(can_edit_team_item(request.user, issue))
    rank = request.POST.get("rank", "")
    rank = int(rank) if rank in {"1", "2", "3"} else None
    if rank == issue.priority:
        rank = None
    issue.set_priority(rank)
    return go_back(request, "/issues/")


@require_POST
def issue_move(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    require(can_edit_team_item(request.user, issue))
    issue.horizon = Issue.LONG if issue.horizon == Issue.SHORT else Issue.SHORT
    issue.priority = None
    issue.save(update_fields=["horizon", "priority"])
    return go_back(request, "/issues/")


def _drop_details(kind, obj_id, user):
    """(team, title, description, source fields) for something dropped to the Issues list."""
    if kind == "measurable":
        m = get_object_or_404(Measurable.objects.select_related("team"), pk=obj_id)
        last = ScoreEntry.objects.filter(measurable=m, value__isnull=False).order_by("-week_start").first()
        detail = f" ({m.format_value(last.value)} vs goal {m.goal_display}, week of {last.week_start:%b %-d})" if last else ""
        return m.team, f"Scorecard: {m.title} off goal{detail}"[:240], "", {"source_measurable": m}, m.owner
    if kind == "rock":
        r = get_object_or_404(Rock.objects.select_related("team"), pk=obj_id)
        label = "off track" if r.status == Rock.OFF_TRACK else r.get_status_display().lower()
        return r.team, f"Rock {label}: {r.title}"[:240], "", {"source_rock": r}, r.owner
    if kind == "headline":
        h = get_object_or_404(Headline.objects.select_related("team"), pk=obj_id)
        return h.team, f"{h.get_kind_display()} headline: {h.text}"[:240], "", {"source_headline": h}, h.author
    raise ValueError(kind)


@require_POST
def drop_to_issues(request):
    """One click: red measurable / off-track rock / headline becomes an open short-term issue."""
    kind = request.POST.get("kind", "")
    try:
        team, title, desc, source, owner = _drop_details(kind, int(request.POST.get("id", 0)), request.user)
    except (ValueError, TypeError):
        return HttpResponse("Unknown item", status=400)
    target_team, _ = scope(request)
    meeting = Meeting.objects.filter(pk=request.POST.get("meeting") or 0).first()
    team = meeting.team if meeting else (team or target_team)
    require(is_admin(request.user) or is_team_member(request.user, team) or (owner and owner.pk == request.user.pk))
    existing = Issue.objects.filter(team=team, status=Issue.OPEN, **source).first()
    if existing:
        issue, created = existing, False
    else:
        issue = Issue.objects.create(
            team=team, title=title, description=desc, owner=owner or request.user, created_by=request.user,
            raised_meeting=meeting, **source,
        )
        created = True
    if is_htmx(request):
        return render(request, "issues/_dropped.html", {"issue": issue, "created": created})
    messages.success(request, "Dropped to Issues." if created else "Already on the Issues list.")
    return go_back(request, "/issues/")
