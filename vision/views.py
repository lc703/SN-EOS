import json

from django import forms
from django.contrib import messages
from django.forms import modelformset_factory
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.forms import PersonField, StyledForm
from core.models import Team, User
from core.permissions import can_view_private_people_notes, is_admin
from core.utils import hx_trigger, is_htmx, require, scope
from issues.models import Issue
from rocks.models import Rock

from .models import VTO, CoreValue, Goal, Seat


class VTOForm(StyledForm, forms.ModelForm):
    class Meta:
        model = VTO
        exclude = ["legacy", "updated_by"]
        widgets = {
            f: forms.Textarea(attrs={"rows": 2})
            for f in ["purpose", "niche", "ten_year_target", "target_market", "proven_process", "guarantee"]
        } | {f: forms.Textarea(attrs={"rows": 5}) for f in ["uniques", "three_year_measurables", "three_year_picture", "one_year_measurables", "one_year_goals"]}


class CoreValueForm(StyledForm, forms.ModelForm):
    class Meta:
        model = CoreValue
        fields = ["name", "description", "sort", "active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


CoreValueFormSet = modelformset_factory(CoreValue, form=CoreValueForm, extra=1, can_delete=True)


class GoalForm(StyledForm, forms.ModelForm):
    owner = PersonField(queryset=User.objects.filter(is_active=True).order_by("name"), required=False)

    class Meta:
        model = Goal
        fields = ["title", "owner", "due_date", "strategy", "tactics", "done"]
        widgets = {
            "strategy": forms.Textarea(attrs={"rows": 2}),
            "tactics": forms.Textarea(attrs={"rows": 4}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }


def goal_edit(request, pk=None):
    require(is_admin(request.user))
    goal = get_object_or_404(Goal, pk=pk) if pk else None
    form = GoalForm(request.POST or None, instance=goal)
    if request.method == "POST":
        if "delete" in request.POST and goal:
            goal.delete()
            return hx_trigger(HttpResponse(status=204), toast="Goal removed.", closePanel=True, vtoChanged=True)
        if form.is_valid():
            created = goal is None
            obj = form.save(commit=False)
            if created:
                obj.sort = Goal.objects.count()
            obj.save()
            if created or not request.POST.get("autosave"):
                return hx_trigger(HttpResponse(status=204), toast="Goal saved.", closePanel=True, vtoChanged=True)
            return hx_trigger(HttpResponse(status=204), vtoChanged=True)
        if request.POST.get("autosave"):
            return hx_trigger(HttpResponse(status=422), toast="A goal needs a title.", kind="error")
    return render(request, "vision/_goal_panel.html", {"form": form, "goal": goal})


def vto(request):
    _, quarter = scope(request)
    leadership = Team.objects.filter(is_leadership=True).first()
    rocks = Rock.objects.filter(quarter=quarter, is_company=True).select_related("owner").prefetch_related("updates") if quarter else []
    issues = (
        Issue.objects.filter(team=leadership, status=Issue.OPEN, horizon=Issue.LONG).select_related("owner")
        if leadership
        else []
    )
    return render(
        request,
        "vision/vto.html",
        {
            "vto": VTO.load(),
            "goals": Goal.objects.select_related("owner").prefetch_related("rocks__updates"),
            "values": CoreValue.objects.filter(active=True),
            "rocks": rocks,
            "long_issues": issues,
            "leadership": leadership,
        },
    )


def vto_edit(request):
    require(is_admin(request.user))
    obj = VTO.load()
    form = VTOForm(request.POST or None, instance=obj)
    values = CoreValueFormSet(request.POST or None, queryset=CoreValue.objects.all(), prefix="cv")
    if request.method == "POST" and form.is_valid() and values.is_valid():
        vto = form.save(commit=False)
        vto.updated_by = request.user
        vto.save()
        values.save()
        messages.success(request, "V/TO saved.")
        return redirect("vto")
    return render(request, "vision/vto_edit.html", {"form": form, "values": values})


class SeatForm(StyledForm, forms.ModelForm):
    person = PersonField(queryset=User.objects.filter(is_active=True).order_by("name"), required=False)

    class Meta:
        model = Seat
        fields = ["title", "person", "person_name", "status", "is_agency", "parent", "team", "roles", "sort"]
        widgets = {"roles": forms.Textarea(attrs={"rows": 6}), "status": forms.RadioSelect}
        labels = {"person_name": "Name (no account)", "parent": "Reports to"}

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        team = team or (self.instance.team if self.instance.team_id else None)
        parents = Seat.objects.select_related("person").order_by("title")
        if team is not None:
            parents = parents.filter(team=team)
        if self.instance.pk:
            parents = parents.exclude(pk__in={self.instance.pk, *self.instance.descendant_ids()})
        self.fields["parent"].queryset = parents
        self.fields["parent"].label_from_instance = lambda s: f"{s.title} ({s.holder})" if s.holder else s.title
        self.fields["status"].required = False
        self.fields["sort"].required = False
        if team is not None and not self.instance.pk:
            self.fields["team"].initial = team.pk

    def clean_status(self):
        return self.cleaned_data.get("status") or Seat.FILLED

    def clean_sort(self):
        return self.cleaned_data.get("sort") or 0

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        node = parent
        while node is not None:
            if self.instance.pk and node.pk == self.instance.pk:
                raise forms.ValidationError("A seat can't report to itself or one of its own reports.")
            node = node.parent
        return parent


def seat_flags(seats, viewer):
    """Attach GWC, People Analyzer and Quarterly Conversation flags to each seat the viewer may see them for."""
    from people.models import OneOnOne, PeopleReview

    people = {s.person_id for s in seats if s.person_id}
    reviews, conversations = {}, {}
    for r in PeopleReview.objects.filter(person_id__in=people).prefetch_related("ratings").order_by("person_id", "-date", "-id"):
        reviews.setdefault(r.person_id, r)
    for o in OneOnOne.objects.filter(person_id__in=people, kind=OneOnOne.QUARTERLY).prefetch_related("scores").order_by("person_id", "-date", "-id"):
        conversations.setdefault(o.person_id, o)
    visible = {pid for pid in people if can_view_private_people_notes(viewer, User(pk=pid))} if not is_admin(viewer) else people
    for s in seats:
        s.flags = None
        if s.person_id not in visible:
            continue
        review, convo = reviews.get(s.person_id), conversations.get(s.person_id)
        flags = {"review": review, "convo": convo, "gwc": None, "pa": None, "red": 0}
        if review:
            flags["gwc"] = [("G", review.gets_it), ("W", review.wants_it), ("C", review.capacity)]
            ratings = [x.rating for x in review.ratings.all()]
            if ratings:
                flags["pa"] = {"plus": ratings.count("+"), "mixed": ratings.count("+/-"), "minus": ratings.count("-")}
        if convo:
            flags["red"] = convo.red_count
        flags["concern"] = bool(
            flags["red"]
            or (review and any(v is False for _, v in flags["gwc"]))
            or (flags["pa"] and flags["pa"]["minus"])
        )
        s.flags = flags
    return seats


def build_tree(seats):
    seats = list(seats)
    ids = {s.pk for s in seats}
    children = {}
    for s in seats:
        key = s.parent_id if s.parent_id in ids else None
        children.setdefault(key, []).append(s)

    def node(seat, depth):
        kids = [node(c, depth + 1) for c in children.get(seat.pk, [])]
        # Leaf groups stack vertically under their manager; anything with deeper levels spreads sideways.
        stack = depth >= 1 and kids and all(not k["children"] for k in kids)
        return {"seat": seat, "depth": depth, "children": kids, "count": sum(1 + k["count"] for k in kids), "layout": "v" if stack else "h"}

    return [node(s, 0) for s in children.get(None, [])]


def chart_context(request):
    team, _ = scope(request)
    seats = list(Seat.objects.filter(team=team).select_related("person", "parent", "parent__person"))
    seat_flags(seats, request.user)
    counts = {Seat.FILLED: 0, Seat.FUTURE: 0, Seat.OPEN: 0}
    for s in seats:
        counts[s.effective_status] += 1
    return {
        "tree": build_tree(seats),
        "seats": sorted(seats, key=lambda s: ((s.parent.title if s.parent else ""), s.sort, s.title)),
        "counts": counts,
        "total": len(seats),
        "agency": sum(1 for s in seats if s.is_agency),
        "concerns": sum(1 for s in seats if s.flags and s.flags["concern"]),
        "can_edit": is_admin(request.user),
    }


def chart(request):
    ctx = chart_context(request)
    if request.GET.get("partial") == "canvas":
        return render(request, "vision/_chart_canvas.html", ctx)
    ctx.update(view=request.GET.get("view", "tree"), wide=True, open_seat=request.GET.get("open", ""))
    return render(request, "vision/chart.html", ctx)


def _panel(request, seat, form=None, team=None):
    team = team or (seat.team if seat else scope(request)[0])
    can_edit = is_admin(request.user)
    ctx = {"seat": seat, "can_edit": can_edit, "team": team}
    if can_edit:
        initial = {}
        if seat is None and request.GET.get("parent"):
            initial["parent"] = request.GET["parent"]
        ctx["form"] = form or SeatForm(instance=seat, team=team, initial=initial)
    if seat:
        seat_flags([seat], request.user)
        ctx["reports"] = list(seat.children.select_related("person"))
    return render(request, "vision/_seat_panel.html", ctx)


def seat_panel(request, pk):
    seat = get_object_or_404(Seat.objects.select_related("person", "parent", "team"), pk=pk)
    return _panel(request, seat)


def _changed(response, message=None, seat=None):
    events = {"chartChanged": {"seat": seat.pk if seat else None}}
    if message:
        events["toast"] = {"value": message}
    response["HX-Trigger"] = json.dumps(events)
    return response


def seat_edit(request, pk=None):
    """Full-page form for no-JS use, side-panel form (htmx) for everything else."""
    require(is_admin(request.user))
    team, _ = scope(request)
    seat = get_object_or_404(Seat, pk=pk) if pk else None
    if request.method != "POST":
        if is_htmx(request):
            return _panel(request, seat, team=team)
        initial = {"parent": request.GET.get("parent")} if seat is None and request.GET.get("parent") else {}
        form = SeatForm(instance=seat, team=(seat.team if seat else team), initial=initial)
        return render(request, "vision/seat_form.html", {"form": form, "obj": seat})
    if seat and "delete" in request.POST:
        Seat.objects.filter(parent=seat).update(parent=seat.parent)
        seat.delete()
        if is_htmx(request):
            resp = HttpResponse("")
            resp["HX-Trigger"] = json.dumps({"chartChanged": {}, "closePanel": True, "toast": {"value": "Seat removed; its reports moved up a level."}})
            return resp
        messages.success(request, "Seat removed; its reports moved up a level.")
        return redirect("chart")
    form = SeatForm(request.POST, instance=seat, team=(seat.team if seat else team))
    if not form.is_valid():
        if is_htmx(request):
            if request.POST.get("autosave"):
                msg = "; ".join(f"{form.fields[f].label if f in form.fields else f}: {' '.join(e)}" for f, e in form.errors.items())
                resp = HttpResponse(status=422)
                resp["HX-Trigger"] = json.dumps({"toast": {"value": msg, "kind": "error"}})
                return resp
            return _panel(request, seat, form=form, team=team)
        return render(request, "vision/seat_form.html", {"form": form, "obj": seat})
    created = seat is None
    seat = form.save()
    if not is_htmx(request):
        messages.success(request, "Seat saved.")
        return redirect("chart")
    if created:
        return _changed(_panel(request, seat), f"Added {seat.title}.", seat)
    return _changed(HttpResponse(status=204), seat=seat)


@require_POST
def seat_move(request, pk):
    """Drag-and-drop re-parenting. `parent` empty = top of the chart."""
    require(is_admin(request.user))
    seat = get_object_or_404(Seat, pk=pk)
    raw = request.POST.get("parent", "")
    parent = get_object_or_404(Seat, pk=int(raw)) if raw.isdigit() else None
    if parent and (parent.pk == seat.pk or parent.pk in seat.descendant_ids()):
        resp = HttpResponse(status=422)
        resp["HX-Trigger"] = json.dumps({"toast": {"value": "A seat can't report to one of its own reports.", "kind": "error"}})
        return resp
    seat.parent = parent
    if parent and parent.team_id and seat.team_id != parent.team_id:
        seat.team_id = parent.team_id
    seat.sort = (Seat.objects.filter(parent=parent).exclude(pk=seat.pk).order_by("-sort").values_list("sort", flat=True).first() or 0) + 1
    seat.save(update_fields=["parent", "team", "sort"])
    who = parent.title if parent else "the top of the chart"
    return _changed(HttpResponse(status=204), f"{seat.title} now reports to {who}.", seat)
