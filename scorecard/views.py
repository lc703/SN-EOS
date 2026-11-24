import datetime as dt
from dataclasses import dataclass, field

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import PersonField, StyledForm, owner_choices
from core.models import monday_of
from core.permissions import can_edit_owned, is_admin, is_team_member
from core.utils import require, scope

from .models import Measurable, Plant, ScoreEntry
from .plants import COMPANY_GROUP, assign_plant, layout, scorecard_for_team, team_for_plant


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
    trailing_label: str = ""
    editable: bool = False
    latest_state: str = ""
    group: str = ""
    group_first: bool = False
    group_note: str = ""
    sub: bool = False

    @property
    def section(self):
        """Company measurables sit in the top section; plant measurables below."""
        return "plants" if self.measurable.plant_id else "company"

    @property
    def plant_label(self):
        """Shown on a plant sub-row in place of the measurable name: Kentucky, Le Roy, Mabel."""
        return self.measurable.plant.name if self.measurable.plant_id else ""

    @property
    def is_red(self):
        return self.latest_state == "red"

    @property
    def spark_values(self):
        return [c.value for c in self.cells]

    @property
    def spark_ok(self):
        return [None if not c.state else c.state == "green" for c in self.cells]

    @property
    def hits(self):
        judged = [c.state for c in self.cells if c.state]
        return (judged.count("green"), len(judged)) if judged else None


def trailing_for(m, values):
    """The measurable's own trailing setting, or the average when none is set."""
    values = [Decimal(v) for v in values if v is not None]
    if not values:
        return None, ""
    if m.unit == Measurable.UNIT_YESNO:
        return f"{sum(1 for v in values if v)}/{len(values)}", "yes"
    if m.trailing == Measurable.TRAIL_TOTAL:
        return sum(values), "total"
    average = sum(values) / len(values)
    # Dollars round once, at display time, so the average never rounds twice.
    return (average if m.is_currency else average.quantize(Decimal("0.01"))), "avg"


def build_rows(measurables, weeks, user, grouped=False, plant=None):
    """One Row per measurable. `grouped` puts Company rows first, then plant rows under a header per name.
    `plant` is a site's own view: Company section on top, then that plant's measurables."""
    measurables = list(measurables)
    groups = {}
    if grouped:
        measurables, groups = layout(measurables, plant)
    entries = {
        (e.measurable_id, e.week_start): e.value
        for e in ScoreEntry.objects.filter(measurable__in=measurables, week_start__in=weeks)
    }
    this_monday = monday_of(timezone.localdate())
    rows = []
    for m in measurables:
        row = Row(measurable=m, editable=can_edit_owned(user, m))
        row.group, row.group_first, row.sub = groups.get(m.pk, ("", False, False))
        if plant is not None and row.group == COMPANY_GROUP:
            row.group_note = "Company numbers, shown on every site"
        values = []
        for w in weeks:
            v = entries.get((m.pk, w))
            on = m.is_on_goal(v)
            state = "" if on is None else ("green" if on else "red")
            row.cells.append(Cell(w, v, m.format_value(v), state, w == this_monday))
            if v is not None:
                values.append(v)
                row.latest_state = state
        trailing, row.trailing_label = trailing_for(m, values)
        row.trailing = trailing if isinstance(trailing, str) else m.format_value(trailing) if trailing is not None else ""
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


def _can_add(user):
    return is_admin(user) or (user.is_authenticated and user.teams.exists())


def scorecard(request):
    team, quarter = scope(request)
    weeks = quarter.weeks() if quarter else []
    measurables, plant = scorecard_for_team(team)
    rows = build_rows(measurables, weeks, request.user, grouped=True, plant=plant)
    can_add = _can_add(request.user)
    return render(
        request,
        "scorecard/scorecard.html",
        {
            "rows": rows,
            "weeks": weeks,
            "cols": ",".join(w.isoformat() for w in weeks),
            "show_trailing": True,
            "show_trend": True,
            "can_add": can_add,
            "sortable": can_add,
            "form": MeasurableForm(initial={"plant": plant}, user=request.user) if can_add else None,
            "plant": plant,
            "wide": True,
        },
    )


@require_POST
def cell(request, pk, week):
    m = get_object_or_404(Measurable.objects.select_related("team", "owner", "plant"), pk=pk)
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
    row.sub = request.POST.get("sub") == "1"
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
            "show_trend": request.POST.get("trend") == "1",
            "sortable": _can_add(request.user),
            "error": error,
        },
    )


class MeasurableForm(StyledForm, forms.ModelForm):
    owner = PersonField(queryset=None, required=False)
    plant = forms.ModelChoiceField(
        Plant.objects.all(), required=False, empty_label="Company",
        help_text="Company for high-level numbers like sales or marketing. Pick a plant for its own numbers.",
    )

    class Meta:
        model = Measurable
        fields = ["title", "plant", "owner", "unit", "goal_compare", "goal", "trailing", "source", "sort"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = owner_choices(None, user=user, instance=self.instance)
        self.fields["goal"].widget.attrs["step"] = "any"
        self.fields["source"].widget.attrs["placeholder"] = "Filled weekly by assistant from Attio"

    def save(self, commit=True):
        m = super().save(commit=False)
        m.team = team_for_plant(m.plant, m.team if m.team_id else None)
        if commit:
            m.save()
        return m


def measurable_new(request):
    require(_can_add(request.user))
    form = MeasurableForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        m = form.save(commit=False)
        require(m.team_id)
        if not m.sort:
            m.sort = Measurable.objects.filter(plant__isnull=True).count()
        m.save()
        messages.success(request, f"Added measurable “{m.title}”.")
        return redirect("scorecard")
    return render(request, "scorecard/measurable_form.html", {"form": form, "obj": None})


def measurable_edit(request, pk):
    m = get_object_or_404(Measurable, pk=pk)
    require(can_edit_owned(request.user, m))
    form = MeasurableForm(request.POST or None, instance=m, user=request.user)
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


@require_POST
def measurable_plant(request, pk):
    """Side-panel field: move a measurable to a plant, or back to Company (blank)."""
    m = get_object_or_404(Measurable.objects.select_related("team", "plant"), pk=pk)
    require(can_edit_owned(request.user, m))
    ref = (request.POST.get("plant") or "").strip()
    plant = None
    if ref and ref.lower() != "company":
        plant = Plant.objects.filter(pk=ref).first() if ref.isdigit() else Plant.find(ref)
        if plant is None:
            return HttpResponse("Unknown plant", status=400)
    changed = assign_plant(m, plant)
    response = HttpResponse(status=204)
    if changed:
        response["HX-Refresh"] = "true"
    return response


def measurable_panel(request, pk):
    """Side panel: trend line against the goal over the last 13 weeks."""
    m = get_object_or_404(Measurable.objects.select_related("team", "owner", "plant"), pk=pk)
    this_monday = monday_of(timezone.localdate())
    weeks = [this_monday - dt.timedelta(weeks=i) for i in range(12, -1, -1)]
    row = build_rows([m], weeks, request.user)[0]
    from core.charts import compact, trend_chart
    from django.utils.safestring import mark_safe

    def axis(v):
        if m.unit == Measurable.UNIT_YESNO:
            return "Yes" if v >= 0.99 else "No" if v <= 0.01 else ""
        if m.is_currency:
            return m.format_value(Decimal(repr(v)))
        return compact(v) + ("%" if m.unit == Measurable.UNIT_PERCENT else "")

    chart = trend_chart([w.strftime("%b %-d") for w in weeks], row.spark_values, goal=m.goal, ok=row.spark_ok,
                        fmt=lambda v: m.format_value(Decimal(repr(v))), axis_fmt=axis, nice_ticks=m.is_currency)
    values = [c.value for c in row.cells if c.value is not None]
    avg = sum(Decimal(v) for v in values) / len(values) if values else None
    hits = row.hits
    return render(request, "scorecard/_panel.html", {
        "m": m, "row": row, "chart": mark_safe(chart),
        "latest": next((c for c in reversed(row.cells) if c.value is not None), None),
        "average": m.format_value(avg if m.is_currency else avg.quantize(Decimal("1") if abs(avg) >= 1000 else Decimal("0.01"))) if values else "",
        "hit_pct": round(100 * hits[0] / hits[1]) if hits else None, "hits": hits,
        "editable": can_edit_owned(request.user, m), "plants": Plant.objects.all(),
    })


@require_POST
def measurables_sort(request):
    """Drag reorder of the Company rows. Plant rows follow their group's first position."""
    require(_can_add(request.user))
    ids = [int(x) for x in request.POST.get("ids", "").split(",") if x.strip().isdigit()]
    allowed = {m.pk for m in Measurable.objects.filter(pk__in=ids).select_related("team")
               if is_admin(request.user) or is_team_member(request.user, m.team) or can_edit_owned(request.user, m)}
    require(allowed or not ids)
    for i, pk in enumerate(ids):
        if pk in allowed:
            Measurable.objects.filter(pk=pk).update(sort=i)
    return HttpResponse(status=204)
