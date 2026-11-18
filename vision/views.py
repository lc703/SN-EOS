from django import forms
from django.contrib import messages
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render

from core.forms import PersonField, StyledForm
from core.models import Team, User
from core.permissions import is_admin
from core.utils import require, scope
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
        fields = ["title", "person", "person_name", "parent", "team", "roles", "sort"]
        widgets = {"roles": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        team = team or (self.instance.team if self.instance.team_id else None)
        parents = Seat.objects.select_related("person").order_by("title")
        if team is not None:
            parents = parents.filter(team=team)
        if self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = parents
        self.fields["parent"].label_from_instance = lambda s: f"{s.title} ({s.holder})" if s.holder else s.title
        if team is not None and not self.instance.pk:
            self.fields["team"].initial = team.pk

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        node = parent
        while node is not None:
            if self.instance.pk and node.pk == self.instance.pk:
                raise forms.ValidationError("A seat can't report to itself or one of its own reports.")
            node = node.parent
        return parent


def build_tree(seats):
    seats = list(seats)
    ids = {s.pk for s in seats}
    children = {}
    for s in seats:
        key = s.parent_id if s.parent_id in ids else None
        children.setdefault(key, []).append(s)

    def node(seat, depth):
        return {"seat": seat, "depth": depth, "children": [node(c, depth + 1) for c in children.get(seat.pk, [])]}

    return [node(s, 0) for s in children.get(None, [])]


def chart(request):
    team, _ = scope(request)
    seats = Seat.objects.filter(team=team).select_related("person", "parent", "parent__person")
    return render(
        request,
        "vision/chart.html",
        {
            "tree": build_tree(seats),
            "seats": seats.order_by("parent__title", "sort", "title"),
            "can_edit": is_admin(request.user),
            "view": request.GET.get("view", "tree"),
            "wide": True,
        },
    )


def seat_edit(request, pk=None):
    require(is_admin(request.user))
    team, _ = scope(request)
    seat = get_object_or_404(Seat, pk=pk) if pk else None
    if seat is None and request.GET.get("parent"):
        parent = Seat.objects.filter(pk=request.GET["parent"]).first()
        initial = {"parent": parent.pk if parent else None}
    else:
        initial = {}
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
