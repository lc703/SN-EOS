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
    """A 1:1 or an EOS Quarterly Conversation (5-5-5: core values, roles, rocks)."""

    ONE_ON_ONE, QUARTERLY = "one_on_one", "quarterly"
    KIND_CHOICES = [(ONE_ON_ONE, "1:1"), (QUARTERLY, "Quarterly Conversation")]

    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=ONE_ON_ONE)
    quarter = models.ForeignKey("core.Quarter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="one_on_ones")
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    date = models.DateField(default=timezone.localdate)
    highlight = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    gets_it = models.BooleanField("Gets it", null=True, blank=True)
    wants_it = models.BooleanField("Wants it", null=True, blank=True)
    capacity = models.BooleanField("Capacity to do it", null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "conversation"
        verbose_name_plural = "1:1s and quarterly conversations"

    def __str__(self):
        return f"{self.get_kind_display()} {self.person} {self.date}"

    @property
    def color_counts(self):
        counts = {"green": 0, "yellow": 0, "red": 0}
        for sc in self.scores.all():
            if sc.color in counts:
                counts[sc.color] += 1
        return counts

    @property
    def is_struggling(self):
        """Any red, or a 'no' on GWC."""
        return self.color_counts["red"] > 0 or False in (self.gets_it, self.wants_it, self.capacity)


class ConversationScore(models.Model):
    """One green/yellow/red cell in a 1:1 or Quarterly Conversation grid."""

    GREEN, YELLOW, RED = "green", "yellow", "red"
    COLOR_CHOICES = [(GREEN, "Green"), (YELLOW, "Yellow"), (RED, "Red")]

    conversation = models.ForeignKey(OneOnOne, on_delete=models.CASCADE, related_name="scores")
    statement = models.ForeignKey(SuccessStatement, null=True, blank=True, on_delete=models.CASCADE, related_name="scores")
    value = models.ForeignKey("vision.CoreValue", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    rock = models.ForeignKey("rocks.Rock", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    color = models.CharField(max_length=6, choices=COLOR_CHOICES, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["value__sort", "statement__sort", "rock__sort", "id"]

    def __str__(self):
        return f"{self.subject}: {self.color}"

    @property
    def subject(self):
        return self.value or self.statement or self.rock


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
