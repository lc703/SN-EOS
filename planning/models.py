from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import LegacyMixin

from .agendas import AGENDAS, ITEM_LABELS


class Session(LegacyMixin):
    """A Quarterly or Annual planning session (the old Battle Planner "offsite")."""

    QUARTERLY, ANNUAL = "quarterly", "annual"
    KIND_CHOICES = [(QUARTERLY, "Quarterly"), (ANNUAL, "Annual")]

    team = models.ForeignKey("core.Team", on_delete=models.CASCADE, related_name="sessions")
    quarter = models.ForeignKey(
        "core.Quarter", null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions",
        help_text="The quarter this session plans. New Rocks go here.",
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=QUARTERLY)
    date = models.DateField(default=timezone.localdate)
    facilitator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    attendees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="planning_sessions")
    current_step = models.CharField(max_length=12, default="segue")
    notes = models.TextField("Cascading messages / notes", blank=True)
    concluded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.team} {self.get_kind_display()} session {self.date:%b %-d, %Y}"

    @property
    def agenda(self):
        return AGENDAS[self.kind]

    @property
    def step_keys(self):
        return [k for k, _, _ in self.agenda]

    @property
    def is_concluded(self):
        return self.concluded_at is not None

    @property
    def average_rating(self):
        scores = [r.rating for r in self.ratings.all() if r.rating]
        return round(sum(scores) / len(scores), 1) if scores else None


class SessionItem(LegacyMixin):
    """One sticky note on a session board: news, working/not working, SWOT, lessons, rock ideas, feedback."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="items")
    step = models.CharField(max_length=12)
    kind = models.CharField(max_length=20)
    text = models.TextField()
    rag = models.CharField(max_length=6, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    about = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="For notes about a person (team health, affirmations).",
    )
    sort = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["sort", "created_at", "id"]

    def __str__(self):
        return self.text[:60]

    @property
    def kind_label(self):
        return ITEM_LABELS.get(self.kind, self.kind.replace("_", " ").capitalize())


class SessionRating(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    rating = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "user"], name="uniq_session_rating")]
