import json

from django import forms
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render

from core.forms import PersonField, StyledForm
from core.models import Team, User
from core.permissions import is_admin
from core.utils import is_htmx, require, scope
from issues.models import Issue
from rocks.models import Rock

from .models import VTO, CoreValue, Seat


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


def vto(request):
    _, quarter = scope(request)
    leadership = Team.objects.filter(is_leadership=True).first()
    rocks = Rock.objects.filter(quarter=quarter, is_company=True).select_related("owner") if quarter else []
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
        fields = ["title", "person", "person_name", "status", "agency", "parent", "team", "roles"]
        widgets = {"roles": forms.Textarea(attrs={"rows": 5, "placeholder": "One per line. Aim for five."})}
        labels = {"person_name": "Or name (no account)", "parent": "Reports to"}

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        team = team or (self.instance.team if self.instance.team_id else None)
        parents = Seat.objects.select_related("person").order_by("title")
        if team is not None:
            parents = parents.filter(team=team)
        if self.instance.pk:
            parents = parents.exclude(pk__in=[self.instance.pk, *descendant_ids(self.instance)])
        self.fields["parent"].queryset = parents
        self.fields["parent"].label_from_instance = lambda s: f"{s.title} ({s.holder})" if s.holder else s.title
        self.fields["status"].widget = forms.RadioSelect(choices=Seat.STATUS_CHOICES)
        self.fields["status"].required = False
        if team is not None and not self.instance.pk:
            self.fields["team"].initial = team.pk

    def clean_status(self):
        return self.cleaned_data.get("status") or self.instance.status or Seat.FILLED

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        if parent is not None and self.instance.pk and would_cycle(self.instance, parent):
            raise forms.ValidationError("A seat can't report to itself or one of its own reports.")
        return parent


def descendant_ids(seat):
    ids, frontier = set(), [seat.pk]
    while frontier:
        nxt = list(Seat.objects.filter(parent_id__in=frontier).exclude(pk__in=ids).values_list("pk", flat=True))
        ids.update(nxt)
        frontier = nxt
    return ids


def would_cycle(seat, parent):
    return parent.pk == seat.pk or parent.pk in descendant_ids(seat)


def build_tree(seats, flags=None):
    """Nested nodes. Parents whose reports are all leaves stack them vertically to keep the chart compact."""
    seats = list(seats)
    flags = flags or {}
    ids = {s.pk for s in seats}
    children = {}
    for s in seats:
        key = s.parent_id if s.parent_id in ids else None
        children.setdefault(key, []).append(s)

    def node(seat, depth):
        kids = [node(c, depth + 1) for c in children.get(seat.pk, [])]
        size = 1 + sum(k["size"] for k in kids)
        return {
            "seat": seat, "depth": depth, "children": kids, "size": size,
            "stack": bool(kids) and all(not k["children"] for k in kids) and depth > 0,
            "flags": flags.get(seat.person_id) if seat.person_id else None,
        }

    return [node(s, 0) for s in children.get(None, [])]


def seat_counts(seats):
    counts = {"total": 0, Seat.FILLED: 0, Seat.FUTURE: 0, Seat.OPEN: 0, "agency": 0}
    for s in seats:
        counts["total"] += 1
        counts[s.display_status] += 1
        counts["agency"] += int(s.agency)
    return counts


def chart(request):
    from people.flags import people_flags

    team, _ = scope(request)
    seats = list(Seat.objects.filter(team=team).select_related("person", "parent", "parent__person"))
    flags = people_flags(request.user, [s.person_id for s in seats])
    status = request.GET.get("status", "")
    listed = sorted(seats, key=lambda s: ((s.parent.title if s.parent else ""), s.sort, s.title))
    if status in {Seat.FILLED, Seat.FUTURE, Seat.OPEN}:
        listed = [s for s in listed if s.display_status == status]
    ctx = {
        "tree": build_tree(seats, flags),
        "seats": [(s, flags.get(s.person_id)) for s in listed],
        "counts": seat_counts(seats),
        "can_edit": is_admin(request.user),
        "view": request.GET.get("view", "tree"),
        "status_filter": status,
        "show_flags": bool(flags),
        "wide": True,
    }
    if is_htmx(request) and request.GET.get("part") == "tree":
        return render(request, "vision/_chart_tree.html", ctx)
    return render(request, "vision/chart.html", ctx)


def _panel_ctx(request, seat, form):
    from people.flags import people_flags

    flags = people_flags(request.user, [seat.person_id]).get(seat.person_id) if seat and seat.person_id else None
    return {"form": form, "obj": seat, "can_edit": is_admin(request.user), "flags": flags,
            "reports": list(seat.children.select_related("person")) if seat else []}


def seat_panel(request, pk=None):
    """Side-panel seat editor. Existing seats autosave on change; new seats save with the button."""
    team, _ = scope(request)
    seat = get_object_or_404(Seat.objects.select_related("person", "parent", "team"), pk=pk) if pk else None
    if request.method == "POST":
        require(is_admin(request.user))
        if seat and "delete" in request.POST:
            Seat.objects.filter(parent=seat).update(parent=seat.parent)
            seat.delete()
            resp = HttpResponse("")
            resp["HX-Trigger"] = json.dumps({"chart:refresh": True, "panel:close": True})
            return resp
        form = SeatForm(request.POST, instance=seat, team=(seat.team if seat else team))
        if not form.is_valid():
            resp = render(request, "vision/_seat_panel.html", _panel_ctx(request, seat, form))
            if seat:
                resp.status_code = 422
            return resp
        created = seat is None
        seat = form.save()
        if created:
            resp = render(request, "vision/_seat_panel.html", _panel_ctx(request, seat, SeatForm(instance=seat)))
            resp["HX-Trigger"] = json.dumps({"chart:refresh": True})
            return resp
        resp = HttpResponse(status=204)
        resp["HX-Trigger"] = json.dumps({"chart:refresh": True})
        return resp
    initial = {}
    if seat is None and request.GET.get("parent"):
        parent = Seat.objects.filter(pk=request.GET["parent"]).first()
        initial = {"parent": parent.pk if parent else None, "team": (parent.team_id if parent else None) or (team.pk if team else None)}
    form = SeatForm(instance=seat, team=(seat.team if seat else team), initial=initial)
    if not is_admin(request.user):
        require(seat is not None)
    return render(request, "vision/_seat_panel.html", _panel_ctx(request, seat, form))


@require_POST
def seat_move(request, pk):
    """Drag to re-parent. parent='' makes it a top-level seat."""
    require(is_admin(request.user))
    seat = get_object_or_404(Seat, pk=pk)
    parent_id = request.POST.get("parent") or None
    parent = get_object_or_404(Seat, pk=parent_id) if parent_id else None
    if parent is not None and would_cycle(seat, parent):
        return JsonResponse({"error": "A seat can't report to one of its own reports."}, status=400)
    seat.parent = parent
    if parent is not None and parent.team_id and seat.team_id != parent.team_id:
        seat.team_id = parent.team_id
    seat.save(update_fields=["parent", "team"])
    return JsonResponse({"ok": True, "seat": seat.pk, "parent": parent.pk if parent else None})


def seat_edit(request, pk=None):
    """Full-page fallback (no JS) for the seat editor."""
    require(is_admin(request.user))
    team, _ = scope(request)
    seat = get_object_or_404(Seat, pk=pk) if pk else None
    initial = {}
    if seat is None and request.GET.get("parent"):
        parent = Seat.objects.filter(pk=request.GET["parent"]).first()
        initial = {"parent": parent.pk if parent else None}
    form = SeatForm(request.POST or None, instance=seat, team=(seat.team if seat else team), initial=initial)
    if request.method == "POST":
        if seat and "delete" in request.POST:
            Seat.objects.filter(parent=seat).update(parent=seat.parent)
            seat.delete()
            messages.success(request, "Seat removed; its reports moved up a level.")
            return redirect("chart")
        if form.is_valid():
            form.save()
            messages.success(request, "Seat saved.")
            return redirect("chart")
    return render(request, "vision/seat_form.html", {"form": form, "obj": seat})
