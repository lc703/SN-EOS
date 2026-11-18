import datetime as dt
from dataclasses import dataclass, field

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import PersonField, StyledForm, people_choices
from core.models import monday_of
from core.permissions import can_edit_owned, is_admin, is_team_member
from core.utils import require, scope

from .models import Measurable, ScoreEntry


@dataclass
class Cell:
    week: dt.date
    value: object
    display: str
    state: str  # "green", "red" or ""
    is_now: bool


@dataclass
class Row:
    measurable: Measurable
    cells: list = field(default_factory=list)
    trailing: str = ""
    editable: bool = False
    latest_state: str = ""

    @property
    def is_red(self):
        return self.latest_state == "red"


def build_rows(measurables, weeks, user):
    measurables = list(measurables)
    entries = {
        (e.measurable_id, e.week_start): e.value
        for e in ScoreEntry.objects.filter(measurable__in=measurables, week_start__in=weeks)
    }
    this_monday = monday_of(timezone.localdate())
    rows = []
    for m in measurables:
        row = Row(measurable=m, editable=can_edit_owned(user, m))
        values = []
        for w in weeks:
            v = entries.get((m.pk, w))
            on = m.is_on_goal(v)
            state = "" if on is None else ("green" if on else "red")
            row.cells.append(Cell(w, v, m.format_value(v), state, w == this_monday))
            if v is not None:
                values.append(v)
                row.latest_state = state
        trailing = m.trailing_value(values)
        row.trailing = m.format_value(trailing) if trailing is not None else ""
        rows.append(row)
    return rows


def parse_cols(raw):
    out = []
    for part in (raw or "").split(","):
        try:
            out.append(dt.date.fromisoformat(part.strip()))
        except ValueError:
            continue
    return out


def scorecard(request):
    team, quarter = scope(request)
    weeks = quarter.weeks() if quarter else []
    measurables = Measurable.objects.filter(team=team, active=True).select_related("owner", "team")
    rows = build_rows(measurables, weeks, request.user)
    can_add = is_admin(request.user) or is_team_member(request.user, team)
    return render(
        request,
        "scorecard/scorecard.html",
        {
            "rows": rows,
            "weeks": weeks,
            "cols": ",".join(w.isoformat() for w in weeks),
            "show_trailing": any(r.measurable.trailing for r in rows),
            "can_add": can_add,
            "form": MeasurableForm(team=team) if can_add else None,
            "wide": True,
        },
    )


@require_POST
def cell(request, pk, week):
    m = get_object_or_404(Measurable.objects.select_related("team", "owner"), pk=pk)
    require(can_edit_owned(request.user, m))
    week = monday_of(dt.date.fromisoformat(week))
    error = ""
    try:
        value = Measurable.parse(request.POST.get("value"), m.unit)
    except ValueError as exc:
        value, error = None, str(exc)
    if not error:
        if value is None:
            ScoreEntry.objects.filter(measurable=m, week_start=week).delete()
        else:
            ScoreEntry.objects.update_or_create(
                measurable=m, week_start=week, defaults={"value": value, "updated_by": request.user}
            )
    cols = parse_cols(request.POST.get("cols"))
    if week not in cols:
        cols.append(week)
    row = build_rows([m], cols, request.user)[0]
    return render(
        request,
        "scorecard/_cell_response.html",
        {
            "row": row,
            "week": week,
            "cols": request.POST.get("cols", ""),
            "mode": request.POST.get("mode", ""),
            "meeting_id": request.POST.get("meeting", ""),
            "show_trailing": request.POST.get("trailing") == "1",
            "error": error,
        },
    )


class MeasurableForm(StyledForm, forms.ModelForm):
    owner = PersonField(queryset=None, required=False)

    class Meta:
        model = Measurable
        fields = ["title", "owner", "unit", "goal_compare", "goal", "trailing", "sort"]

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        team = team or (self.instance.team if self.instance.team_id else None)
        self.fields["owner"].queryset = people_choices(team, include=[self.instance.owner_id])
        self.fields["goal"].widget.attrs["step"] = "any"


def measurable_new(request):
    team, _ = scope(request)
    require(is_admin(request.user) or is_team_member(request.user, team))
    form = MeasurableForm(request.POST or None, team=team)
    if request.method == "POST" and form.is_valid():
        m = form.save(commit=False)
        m.team = team
        if not m.sort:
            m.sort = Measurable.objects.filter(team=team).count()
        m.save()
        messages.success(request, f"Added measurable “{m.title}”.")
        return redirect("scorecard")
    return render(request, "scorecard/measurable_form.html", {"form": form, "obj": None})


def measurable_edit(request, pk):
    m = get_object_or_404(Measurable, pk=pk)
    require(can_edit_owned(request.user, m))
    form = MeasurableForm(request.POST or None, instance=m)
    if request.method == "POST":
        if "archive" in request.POST:
            m.active = False
            m.save(update_fields=["active"])
            messages.success(request, f"Archived “{m.title}”.")
            return redirect("scorecard")
        if form.is_valid():
            form.save()
            messages.success(request, "Measurable saved.")
            return redirect("scorecard")
    return render(request, "scorecard/measurable_form.html", {"form": form, "obj": m})
