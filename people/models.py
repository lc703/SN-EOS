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


GREEN, YELLOW, RED = "green", "yellow", "red"
RAG_CHOICES = [(GREEN, "Green"), (YELLOW, "Yellow"), (RED, "Red")]


class OneOnOne(LegacyMixin):
    """A Quarterly Conversation (or a lighter monthly 1:1): G/Y/R per success statement and core value."""

    QUARTERLY, CHECKIN = "quarterly", "checkin"
    KIND_CHOICES = [(QUARTERLY, "Quarterly Conversation"), (CHECKIN, "1:1 check-in")]

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="one_on_ones")
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=QUARTERLY)
    date = models.DateField(default=timezone.localdate)
    highlight = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
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

    @property
    def is_complete(self):
        return self.completed_at is not None

    def score_map(self):
        """{("ss", id) or ("cv", id): score}"""
        out = {}
        for s in self.scores.all():
            key = ("ss", s.statement_id) if s.statement_id else ("cv", s.value_id)
            out[key] = s
        return out

    @property
    def red_count(self):
        return sum(1 for s in self.scores.all() if s.rag == RED)

    @property
    def struggling(self):
        return self.red_count > 0


class OneOnOneScore(models.Model):
    one_on_one = models.ForeignKey(OneOnOne, on_delete=models.CASCADE, related_name="scores")
    statement = models.ForeignKey(SuccessStatement, null=True, blank=True, on_delete=models.CASCADE, related_name="scores")
    value = models.ForeignKey("vision.CoreValue", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    rag = models.CharField(max_length=6, choices=RAG_CHOICES, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["one_on_one", "statement"], name="uniq_score_statement"),
            models.UniqueConstraint(fields=["one_on_one", "value"], name="uniq_score_value"),
            models.CheckConstraint(
                condition=models.Q(statement__isnull=False, value__isnull=True) | models.Q(statement__isnull=True, value__isnull=False),
                name="score_statement_xor_value",
            ),
        ]

    def __str__(self):
        return f"{self.one_on_one} {self.statement or self.value}: {self.rag}"


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
