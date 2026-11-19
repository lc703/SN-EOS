import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import PersonField, StyledForm, people_choices
from core.models import monday_of
from core.permissions import can_edit_owned, is_admin, is_team_member
from core.charts import GREEN, RED, line_chart
from core.utils import is_htmx, require, scope

from .models import Measurable, ScoreEntry


@dataclass
class Cell:
    week: dt.date
    value: object
    display: str
    state: str  # "green", "red" or ""
    is_now: bool
    is_future: bool = False


@dataclass
class Row:
    measurable: Measurable
    cells: list = field(default_factory=list)
    trailing: str = ""
    editable: bool = False
    latest_state: str = ""
    average: str = ""
    average_state: str = ""
    total: str = ""
    on_goal: int = 0
    scored: int = 0

    @property
    def is_red(self):
        return self.latest_state == "red"

    @property
    def spark(self):
        return [c.value for c in self.cells]

    @property
    def spark_states(self):
        return [c.state for c in self.cells]

    @property
    def hit_rate(self):
        return round(100 * self.on_goal / self.scored) if self.scored else None


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
            row.cells.append(Cell(w, v, m.format_value(v), state, w == this_monday, w > this_monday))
            if v is not None:
                values.append(v)
                row.latest_state = state
                if on is not None:
                    row.scored += 1
                    row.on_goal += 1 if on else 0
        trailing = m.trailing_value(values)
        row.trailing = m.format_value(trailing) if trailing is not None else ""
        if values:
            avg = (sum(Decimal(v) for v in values) / len(values)).quantize(Decimal("0.01"))
            row.average = m.format_value(avg)
            on = m.is_on_goal(avg)
            row.average_state = "" if on is None else ("green" if on else "red")
            if m.unit in (Measurable.UNIT_NUMBER, Measurable.UNIT_CURRENCY):
                row.total = m.format_value(sum(Decimal(v) for v in values))
        rows.append(row)
    return rows


def week_summary(rows, weeks):
    """[(week, on_goal, scored)] across all rows: the footer of the grid."""
    out = []
    for i, w in enumerate(weeks):
        states = [r.cells[i].state for r in rows if i < len(r.cells) and r.cells[i].state]
        out.append({"week": w, "on": states.count("green"), "scored": len(states),
                    "pct": round(100 * states.count("green") / len(states)) if states else None})
    return out


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
    mine = request.GET.get("owner") == "me"
    if mine:
        measurables = measurables.filter(owner=request.user)
    rows = build_rows(measurables, weeks, request.user)
    can_add = is_admin(request.user) or is_team_member(request.user, team)
    summary = week_summary(rows, weeks)
    this_monday = monday_of(timezone.localdate())
    last = next((s for s in reversed(summary) if s["week"] < this_monday and s["scored"]), None)
    missing = [r for r in rows if r.editable and any(c.week == this_monday - dt.timedelta(weeks=1) and c.value is None for c in r.cells)]
    return render(
        request,
        "scorecard/scorecard.html",
        {
            "rows": rows,
            "weeks": weeks,
            "cols": ",".join(w.isoformat() for w in weeks),
            "show_trailing": True,
            "summary": summary,
            "summary_bars": [(str(i + 1), x["pct"]) for i, x in enumerate(summary)],
            "last": last,
            "last_segments": [(last["on"], GREEN, "On goal"), (last["scored"] - last["on"], RED, "Off goal")] if last else [],
            "missing": missing,
            "mine": mine,
            "can_add": can_add,
            "can_reorder": can_add and not mine,
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
    mode = request.POST.get("mode", "")
    footer = None
    if mode != "home":
        team_rows = build_rows(Measurable.objects.filter(team=m.team, active=True), [week], request.user)
        footer = week_summary(team_rows, [week])[0]
    return render(
        request,
        "scorecard/_cell_response.html",
        {
            "row": row,
            "week": week,
            "cols": request.POST.get("cols", ""),
            "mode": mode,
            "meeting_id": request.POST.get("meeting", ""),
            "show_trailing": request.POST.get("trailing") == "1",
            "error": error,
            "footer": footer,
        },
    )


def axis_label(m, v):
    if abs(v) >= 10000:
        text = f"{v / 1000:,.0f}k"
        return f"${text}" if m.unit == Measurable.UNIT_CURRENCY else text
    return m.format_value(Decimal(str(round(v, 1))))


def measurable_panel(request, pk):
    m = get_object_or_404(Measurable.objects.select_related("owner", "team"), pk=pk)
    today = timezone.localdate()
    this_monday = monday_of(today)
    weeks = [this_monday - dt.timedelta(weeks=i) for i in range(25, -1, -1)]
    row = build_rows([m], weeks, request.user)[0]
    points = [(c.week.strftime("%b %-d"), c.value, c.state) for c in row.cells if c.week < this_monday or c.value is not None]
    while points and points[0][1] is None:
        points.pop(0)
    values = [c.value for c in row.cells if c.value is not None]
    latest = next((c for c in reversed(row.cells) if c.value is not None), None)
    editable = can_edit_owned(request.user, m)
    chart = line_chart(points, goal=m.goal if m.unit != Measurable.UNIT_YESNO else None, fmt=lambda v: axis_label(m, v), title=m.title, width=440, height=210) if len(points) > 1 else ""
    return render(request, "scorecard/_panel.html", {
        "m": m, "row": row, "chart": chart, "latest": latest,
        "best": m.format_value(max(values) if m.goal_compare != Measurable.LTE else min(values)) if values else "",
        "editable": editable, "form": MeasurableForm(instance=m) if editable else None,
        "recent": [c for c in reversed(row.cells) if c.value is not None][:8],
    })


@require_POST
def measurable_reorder(request):
    team, _ = scope(request)
    require(is_admin(request.user) or is_team_member(request.user, team))
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    by_id = {m.pk: m for m in Measurable.objects.filter(team=team, pk__in=ids)}
    for sort, pk in enumerate(ids):
        if pk in by_id and by_id[pk].sort != sort:
            by_id[pk].sort = sort
            by_id[pk].save(update_fields=["sort"])
    return HttpResponse(status=204)


class MeasurableForm(StyledForm, forms.ModelForm):
    owner = PersonField(queryset=None, required=False)

    class Meta:
        model = Measurable
        fields = ["title", "owner", "unit", "goal_compare", "goal", "trailing", "sort"]
        labels = {"goal_compare": "Goal is", "trailing": "Highlight column"}

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        team = team or (self.instance.team if self.instance.team_id else None)
        self.fields["owner"].queryset = people_choices(team, include=[self.instance.owner_id])
        self.fields["goal"].widget.attrs["step"] = "any"
        self.fields["sort"].required = False

    def clean_sort(self):
        return self.cleaned_data.get("sort") or 0


def _changed(response, message=None, close=False):
    events = {"scorecardChanged": True}
    if message:
        events["toast"] = {"value": message}
    if close:
        events["closePanel"] = True
    response["HX-Trigger"] = json.dumps(events)
    return response


def _form_errors(form):
    resp = HttpResponse(status=422)
    msg = "; ".join(f"{form.fields[f].label if f in form.fields else f}: {' '.join(e)}" for f, e in form.errors.items())
    resp["HX-Trigger"] = json.dumps({"toast": {"value": msg, "kind": "error"}})
    return resp


def measurable_new(request):
    team, _ = scope(request)
    require(is_admin(request.user) or is_team_member(request.user, team))
    form = MeasurableForm(request.POST or None, team=team, initial={"owner": request.user.pk})
    if request.method == "POST" and form.is_valid():
        m = form.save(commit=False)
        m.team = team
        if not m.sort:
            m.sort = Measurable.objects.filter(team=team).count()
        m.save()
        if is_htmx(request):
            return _changed(HttpResponse(""), f"Added measurable “{m.title}”.", close=True)
        messages.success(request, f"Added measurable “{m.title}”.")
        return redirect("scorecard")
    if is_htmx(request):
        if request.method == "POST":
            return _form_errors(form)
        return render(request, "scorecard/_new_panel.html", {"form": form})
    return render(request, "scorecard/measurable_form.html", {"form": form, "obj": None})


def measurable_edit(request, pk):
    m = get_object_or_404(Measurable, pk=pk)
    require(can_edit_owned(request.user, m))
    form = MeasurableForm(request.POST or None, instance=m)
    if request.method == "POST":
        if "archive" in request.POST:
            m.active = False
            m.save(update_fields=["active"])
            if is_htmx(request):
                return _changed(HttpResponse(""), f"Archived “{m.title}”. Its history is kept.", close=True)
            messages.success(request, f"Archived “{m.title}”.")
            return redirect("scorecard")
        if form.is_valid():
            form.save()
            if is_htmx(request):
                return _changed(HttpResponse(status=204))
            messages.success(request, "Measurable saved.")
            return redirect("scorecard")
        if is_htmx(request):
            return _form_errors(form)
    return render(request, "scorecard/measurable_form.html", {"form": form, "obj": m})
