import datetime as dt

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.forms import PersonField, StyledForm, owner_choices
from core.models import Team
from core.permissions import can_edit_team_item, is_admin, is_team_member
from core.scoping import company_items, for_team, is_rollup, is_site
from core.l10 import l10_return
from core.utils import go_back, is_htmx, require, scope, stash_form_errors
from meetings.models import Headline, Meeting
from rocks.models import Rock
from scorecard.models import Measurable, ScoreEntry
from todos.models import default_due
from todos.views import TodoForm, create_todo

from .models import Issue


class IssueForm(StyledForm, forms.ModelForm):
    owner = PersonField(queryset=None, required=False)
    team = forms.ModelChoiceField(queryset=Team.objects.order_by("sort", "name"), required=False, label="Site", empty_label=None)

    class Meta:
        model = Issue
        fields = ["title", "team", "owner", "horizon", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    full_width = ["title"]

    def __init__(self, *args, team=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.current_team = self.instance.team if self.instance.team_id else None
        default = self.current_team or team
        self.default_team = default
        self.fields["team"].initial = default
        owners = owner_choices(default, user=user, instance=self.instance)
        picked = self.data.get("team") if self.is_bound else None
        if picked and str(picked).isdigit() and (other := Team.objects.filter(pk=int(picked)).first()) and other != default:
            owners = (owners | owner_choices(other, user=user, instance=self.instance)).distinct()
        self.fields["owner"].queryset = owners

    def clean_team(self):
        team = self.cleaned_data.get("team") or self.default_team
        if team is None:
            raise forms.ValidationError("Pick a site.")
        if team != self.current_team and self.user is not None:
            if not (is_admin(self.user) or is_team_member(self.user, team)):
                raise forms.ValidationError(f"You're not on the {team.name} team.")
        return team


def mark_editable(items, user):
    """Rows from another team (Company on a site view) are editable only under the normal item rules."""
    items = list(items)
    for i in items:
        i.editable = can_edit_team_item(user, i)
    return items


def open_issues(team, horizon=Issue.SHORT):
    return for_team(Issue.objects.filter(horizon=horizon, status=Issue.OPEN), team).select_related("owner", "team")


def issues_list(request):
    team, _ = scope(request)
    horizon = Issue.LONG if request.GET.get("list") == "long" else Issue.SHORT
    sites, site = (list(Team.objects.order_by("sort", "name")), None)
    if is_rollup(team):
        slug = request.GET.get("site", "")
        site = next((t for t in sites if t.slug == slug), None)
    else:
        sites = []
    scoped = lambda qs: qs.filter(team=site) if site else for_team(qs, team)
    issues = scoped(Issue.objects.filter(horizon=horizon, status=Issue.OPEN)).select_related("owner", "team").prefetch_related("todos")
    solved = scoped(Issue.objects.filter(status=Issue.SOLVED)).select_related("owner", "team").order_by("-solved_at", "-created_at")[:15]
    can_add = is_admin(request.user) or is_team_member(request.user, team)
    company = company_items(Issue.objects.filter(horizon=horizon, status=Issue.OPEN), team).select_related("owner", "team").prefetch_related("todos")
    return render(
        request,
        "issues/issues.html",
        {
            "issues": issues,
            "company_issues": mark_editable(company, request.user),
            "company_counts": {h: company_items(Issue.objects.filter(horizon=h, status=Issue.OPEN), team).count() for h in (Issue.SHORT, Issue.LONG)} if is_site(team) else {},
            "solved": solved,
            "horizon": horizon,
            "counts": {h: scoped(Issue.objects.filter(horizon=h, status=Issue.OPEN)).count() for h in (Issue.SHORT, Issue.LONG)},
            "sites": sites,
            "site": site,
            "can_add": can_add,
            "can_edit": can_add,
            "people": owner_choices(team, user=request.user),
            "default_due": default_due(),
        },
    )


@require_POST
def issue_new(request):
    mid = request.POST.get("meeting", "")
    meeting = Meeting.objects.select_related("team").filter(pk=int(mid)).first() if mid.isdigit() else None
    if meeting is not None:
        # Raised from inside an L10: the meeting decides the team and permission, not whichever site the
        # session happens to be browsing, so the issue always lands on that meeting's IDS list.
        team = meeting.team
        require(is_admin(request.user) or is_team_member(request.user, team))
        data = request.POST.copy()
        data["horizon"] = Issue.SHORT
        if not team.is_leadership or not data.get("team"):
            data["team"] = str(team.pk)
    else:
        team, _ = scope(request)
        require(is_admin(request.user) or is_team_member(request.user, team))
        data = request.POST
    form = IssueForm(data, team=team, user=request.user)
    if form.is_valid():
        issue = form.save(commit=False)
        issue.created_by = request.user
        if not issue.owner_id:
            issue.owner = request.user
        issue.raised_meeting = meeting
        issue.save()
    else:
        stash_form_errors(request, "issue", form)
    return go_back(request, f"/meetings/{meeting.pk}/?s=ids" if meeting else "/issues/")


def issue_detail(request, pk):
    issue = get_object_or_404(Issue.objects.select_related("team", "owner", "source_measurable", "source_rock", "source_headline"), pk=pk)
    editable = can_edit_team_item(request.user, issue)
    before = (issue.team_id, issue.horizon)
    form = IssueForm(request.POST or None, instance=issue, user=request.user)
    if request.method == "POST":
        require(editable)
        if "delete" in request.POST:
            issue.delete_and_recompact()
            messages.success(request, "Issue deleted.")
            back = l10_return(request)
            return redirect(back["url"]) if back else redirect("issues")
        if form.is_valid():
            form.save()
            if (issue.team_id, issue.horizon) != before:
                issue.clear_priority_if_taken()
            messages.success(request, "Issue saved.")
            back = l10_return(request)
            mid = request.GET.get("meeting", "")
            params = []
            if mid.isdigit():
                params.append(f"meeting={mid}")
            if back:
                params.append(back["qs"][1:])
            return redirect(reverse("issue_detail", args=[issue.pk]) + ("?" + "&".join(params) if params else ""))
    return render(
        request,
        "issues/issue_detail.html",
        {
            "issue": issue,
            "form": form,
            "editable": editable,
            "todos": issue.todos.select_related("owner"),
            "todo_form": TodoForm(team=issue.team, user=request.user),
            "people": owner_choices(issue.team, user=request.user),
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
def issue_delete(request, pk):
    """Delete an issue (not the same as solving it). Owner, team members and admins; ranks below it move up."""
    issue = get_object_or_404(Issue, pk=pk)
    require(can_edit_team_item(request.user, issue))
    title = issue.title
    reranked = issue.delete_and_recompact()
    if is_htmx(request):
        resp = HttpResponse("")
        if reranked or request.POST.get("refresh") == "1":
            resp["HX-Refresh"] = "true"
        return resp
    messages.success(request, f"Deleted “{title}”.")
    gone = f"/issues/{pk}/"
    target = request.POST.get("next") or request.META.get("HTTP_REFERER") or ""
    if gone in target or not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect("issues")
    return redirect(target)


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
        m = get_object_or_404(Measurable.objects.select_related("team", "plant"), pk=obj_id)
        last = ScoreEntry.objects.filter(measurable=m, value__isnull=False).order_by("-week_start").first()
        detail = f" ({m.format_value(last.value)} vs goal {m.goal_display}, week of {last.week_start:%b %-d})" if last else ""
        return m.team, f"Scorecard: {m.title}{f' ({m.plant.name})' if m.plant_id else ''} off goal{detail}"[:240], "", {"source_measurable": m}, m.owner
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
