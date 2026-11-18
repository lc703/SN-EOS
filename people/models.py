from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import LegacyMixin


class SuccessStatement(LegacyMixin):
    """What success looks like in a person's seat; the agenda for their 1:1s."""

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="success_statements")
    text = models.TextField()
    standard = models.TextField(blank=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.text[:60]


class OneOnOne(LegacyMixin):
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="one_on_ones")
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "1:1"
        verbose_name_plural = "1:1s"

    def __str__(self):
        return f"1:1 {self.person} {self.date}"


class PeopleReview(models.Model):
    """People Analyzer-lite: core values (+, +/-, -) and GWC."""

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="people_reviews")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    date = models.DateField(default=timezone.localdate)
    gets_it = models.BooleanField("Gets it", null=True, blank=True)
    wants_it = models.BooleanField("Wants it", null=True, blank=True)
    capacity = models.BooleanField("Capacity to do it", null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Review {self.person} {self.date}"

    @property
    def gwc_ok(self):
        return bool(self.gets_it and self.wants_it and self.capacity)


class ValueRating(models.Model):
    PLUS, MIXED, MINUS = "+", "+/-", "-"
    CHOICES = [(PLUS, "+"), (MIXED, "+/-"), (MINUS, "-")]

    review = models.ForeignKey(PeopleReview, on_delete=models.CASCADE, related_name="ratings")
    value = models.ForeignKey("vision.CoreValue", on_delete=models.CASCADE)
    rating = models.CharField(max_length=3, choices=CHOICES)

    class Meta:
        unique_together = [("review", "value")]
        ordering = ["value__sort"]
