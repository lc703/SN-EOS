from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from core.models import LegacyMixin
from core.money import format_dollars


COMPANY = "Company"


class Plant(LegacyMixin):
    """A site that runs its own numbers (Kentucky, Le Roy, Mabel). A measurable with no plant is a Company measurable."""

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @classmethod
    def find(cls, ref):
        """A plant by name or slug, or None. "company" and blank are not plants."""
        text = (ref or "").strip().lower()
        if not text or text == "company":
            return None
        key = slugify(text)
        for plant in cls.objects.all():
            if plant.name.lower() == text or plant.slug == key:
                return plant
        return None


class Measurable(LegacyMixin):
    UNIT_NUMBER = "number"
    UNIT_PERCENT = "percent"
    UNIT_CURRENCY = "currency"
    UNIT_YESNO = "yesno"
    UNIT_CHOICES = [
        (UNIT_NUMBER, "Number"),
        (UNIT_PERCENT, "%"),
        (UNIT_CURRENCY, "Currency ($)"),
        (UNIT_YESNO, "Yes / No"),
    ]
    GTE, LTE, EQ = "gte", "lte", "eq"
    COMPARE_CHOICES = [(GTE, "≥"), (LTE, "≤"), (EQ, "=")]
    TRAIL_NONE, TRAIL_AVG, TRAIL_TOTAL = "", "avg", "total"
    TRAIL_CHOICES = [(TRAIL_NONE, "None"), (TRAIL_AVG, "Average"), (TRAIL_TOTAL, "Total")]

    team = models.ForeignKey("core.Team", on_delete=models.CASCADE, related_name="measurables")
    plant = models.ForeignKey(
        Plant, null=True, blank=True, on_delete=models.SET_NULL, related_name="measurables",
        help_text="Leave blank for a Company measurable (sales, marketing and other high-level numbers).",
    )
    title = models.CharField(max_length=160)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="measurables"
    )
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default=UNIT_NUMBER)
    goal_compare = models.CharField("Goal is", max_length=3, choices=COMPARE_CHOICES, default=GTE)
    goal = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, help_text="For Yes/No, 1 = Yes, 0 = No."
    )
    trailing = models.CharField(
        "Trailing column", max_length=5, choices=TRAIL_CHOICES, default=TRAIL_NONE, blank=True
    )
    source = models.CharField(
        "Source note", max_length=160, blank=True,
        help_text="Where the numbers come from, shown under the name. E.g. “Filled weekly by assistant from Attio”.",
    )
    sort = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["team__sort", "sort", "id"]

    def __str__(self):
        return self.title

    @property
    def plant_name(self):
        return self.plant.name if self.plant_id else COMPANY

    @property
    def is_currency(self):
        return self.unit == self.UNIT_CURRENCY

    def is_on_goal(self, value):
        """True/False against the goal, or None when there is no value or no goal."""
        if value is None or self.goal is None:
            return None
        value, goal = Decimal(value), Decimal(self.goal)
        if self.goal_compare == self.GTE:
            return value >= goal
        if self.goal_compare == self.LTE:
            return value <= goal
        return value == goal

    def format_value(self, value):
        if value is None:
            return ""
        value = Decimal(value)
        if self.unit == self.UNIT_YESNO:
            return "Yes" if value else "No"
        if self.unit == self.UNIT_CURRENCY:
            return format_dollars(value)
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
        if self.unit == self.UNIT_PERCENT:
            return f"{text}%"
        return text

    @property
    def goal_display(self):
        if self.goal is None:
            return "—"
        if self.unit == self.UNIT_YESNO:
            return "Yes" if self.goal else "No"
        return f"{self.get_goal_compare_display()} {self.format_value(self.goal)}"

    def trailing_value(self, values):
        values = [Decimal(v) for v in values if v is not None]
        if not values or not self.trailing:
            return None
        total = sum(values)
        if self.trailing == self.TRAIL_TOTAL:
            return total
        return (total / len(values)).quantize(Decimal("0.01"))

    @staticmethod
    def parse(raw, unit):
        raw = (raw or "").strip().replace(",", "").replace("$", "").replace("%", "")
        if raw == "":
            return None
        if unit == Measurable.UNIT_YESNO:
            low = raw.lower()
            if low in {"y", "yes", "1", "true"}:
                return Decimal(1)
            if low in {"n", "no", "0", "false"}:
                return Decimal(0)
            raise ValueError("Enter yes or no")
        try:
            return Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError("Enter a number") from exc


class ScoreEntry(models.Model):
    measurable = models.ForeignKey(Measurable, on_delete=models.CASCADE, related_name="entries")
    week_start = models.DateField()
    value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("measurable", "week_start")]
        ordering = ["week_start"]

    def __str__(self):
        return f"{self.measurable} {self.week_start}: {self.value}"

    @property
    def on_goal(self):
        return self.measurable.is_on_goal(self.value)
