"""Load weekly Scorecard values from a CSV: metric name, facility, week_start, value.

Built for the rows the old app filled by itself (iQuote and Attio), so a backfill can be loaded in one go.
Every row is an upsert on (measurable, week): a new week is created, a different value replaces the old one,
the same value is left alone. A row that can't be read is skipped and reported; it never stops the load.
"""

import csv
import datetime as dt
import io
from collections import Counter
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from core.models import Team, monday_of

from .models import Measurable, Plant, ScoreEntry

ALIASES = {
    "metric": {"metric", "metric_name", "measurable", "measurable_name", "name", "title"},
    "facility": {"facility", "team", "location", "site"},
    "week_start": {"week_start", "week", "week_of", "date", "week_starting"},
    "value": {"value", "actual", "amount", "total"},
}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y")


@dataclass
class ValuesResult:
    counts: Counter = field(default_factory=Counter)
    notes: list = field(default_factory=list)


def _key(name):
    return (name or "").strip().lower().replace(" ", "_").replace("-", "_")


def _date(raw):
    raw = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


class _Lookup:
    """Finds a measurable by name and plant. The facility column is the plant; blank or "Company" is Company."""

    def __init__(self):
        self.measurables = list(Measurable.objects.select_related("plant").order_by("-active", "id"))

    def find(self, metric, facility):
        """(measurable, problem). Exactly one of the two is None."""
        title = metric.strip().lower()
        named = [m for m in self.measurables if m.title.strip().lower() == title]
        company = not facility or facility.strip().lower() == "company"
        if company:
            named = [m for m in named if m.plant_id is None] or named
        else:
            plant = Plant.find(facility)
            if plant is None:
                team = Team.objects.filter(short_code__iexact=facility.strip()).first()
                plant = Plant.find(team.name) if team else None
            if plant is None:
                return None, f"unknown facility '{facility}'"
            named = [m for m in named if m.plant_id == plant.pk]
        if not named:
            where = f" for {facility}" if facility else ""
            return None, f"no measurable '{metric}'{where}"
        active = [m for m in named if m.active]
        named = active or named
        if len(named) > 1:
            return None, f"'{metric}' is on several measurables; add a facility"
        return named[0], None


def load_values_csv(text, user=None):
    """Upsert every readable row. Returns ValuesResult(counts, notes)."""
    result = ValuesResult()
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    columns = {}
    for header in reader.fieldnames or []:
        for want, names in ALIASES.items():
            if _key(header) in names and want not in columns:
                columns[want] = header
    missing = [w for w in ("metric", "week_start", "value") if w not in columns]
    if missing:
        raise ValueError(
            f"CSV needs columns for {', '.join(missing)}. Expected: metric, facility, week_start, value."
        )
    lookup = _Lookup()
    problems = Counter()
    with transaction.atomic():
        for line, row in enumerate(reader, start=2):
            metric = (row.get(columns["metric"]) or "").strip()
            if not metric and not any((v or "").strip() for v in row.values()):
                continue
            facility = (row.get(columns["facility"]) or "").strip() if "facility" in columns else ""
            raw_value = (row.get(columns["value"]) or "").strip()
            week = _date(row.get(columns["week_start"]))
            if not metric or week is None:
                problems[f"line {line}: needs a metric and a readable week_start"] += 1
                result.counts["skipped"] += 1
                continue
            if raw_value == "":
                result.counts["skipped"] += 1
                continue
            m, problem = lookup.find(metric, facility)
            if m is None:
                problems[problem] += 1
                result.counts["skipped"] += 1
                continue
            try:
                value = Measurable.parse(raw_value, m.unit)
                if value is None or not value.is_finite():
                    raise ValueError
                value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except (ValueError, ArithmeticError):
                problems[f"line {line}: can't read '{raw_value}' for {m.title}"] += 1
                result.counts["skipped"] += 1
                continue
            monday = monday_of(week)
            entry = ScoreEntry.objects.filter(measurable=m, week_start=monday).first()
            if entry is None:
                ScoreEntry.objects.create(measurable=m, week_start=monday, value=value, updated_by=user)
                result.counts["created"] += 1
            elif entry.value != value:
                entry.value, entry.updated_by = value, user
                entry.save()
                result.counts["updated"] += 1
            else:
                result.counts["unchanged"] += 1
    for message, n in problems.items():
        result.notes.append(f"{message}" + (f" ({n} rows)" if n > 1 else ""))
    return result
