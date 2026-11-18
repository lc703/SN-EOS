from django.conf import settings
from django.db import models

from core.models import LegacyMixin


class CoreValue(LegacyMixin):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    sort = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.name


class VTO(models.Model):
    """The company Vision/Traction Organizer. One row."""

    purpose = models.TextField("Purpose / cause / passion", blank=True)
    niche = models.TextField("Niche", blank=True)
    ten_year_target = models.TextField("10-year target", blank=True)
    target_market = models.TextField("Target market (the list)", blank=True)
    uniques = models.TextField("Three uniques", blank=True, help_text="One per line.")
    proven_process = models.TextField("Proven process", blank=True)
    guarantee = models.TextField("Guarantee", blank=True)
    three_year_date = models.CharField("Future date", max_length=60, blank=True)
    three_year_revenue = models.CharField("Revenue", max_length=120, blank=True)
    three_year_profit = models.CharField("Profit", max_length=120, blank=True)
    three_year_measurables = models.TextField("Measurables", blank=True, help_text="One per line.")
    three_year_picture = models.TextField("What does it look like?", blank=True, help_text="One per line.")
    one_year_date = models.CharField("Future date", max_length=60, blank=True)
    one_year_revenue = models.CharField("Revenue", max_length=120, blank=True)
    one_year_profit = models.CharField("Profit", max_length=120, blank=True)
    one_year_measurables = models.TextField("Measurables", blank=True, help_text="One per line.")
    one_year_goals = models.TextField("Goals for the year", blank=True, help_text="One per line.")
    legacy = models.JSONField(default=dict, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = "V/TO"
        verbose_name_plural = "V/TO"

    def __str__(self):
        return "V/TO"

    @classmethod
    def load(cls):
        obj = cls.objects.order_by("pk").first()
        return obj or cls.objects.create()


class Seat(LegacyMixin):
    team = models.ForeignKey("core.Team", null=True, blank=True, on_delete=models.SET_NULL, related_name="seats")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    title = models.CharField(max_length=120)
    person = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="seats"
    )
    person_name = models.CharField(
        max_length=120, blank=True, help_text="Used when the person has no account (or the seat is open)."
    )
    roles = models.TextField("Roles / responsibilities", blank=True, help_text="One per line; aim for five.")
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.title

    @property
    def holder(self):
        if self.person_id:
            return self.person.display_name
        return self.person_name

    @property
    def role_list(self):
        return [r.strip() for r in self.roles.splitlines() if r.strip()]
