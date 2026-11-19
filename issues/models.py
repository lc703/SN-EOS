from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import LegacyMixin


class Issue(LegacyMixin):
    SHORT, LONG = "short", "long"
    HORIZON_CHOICES = [(SHORT, "Short-term"), (LONG, "Long-term")]
    OPEN, SOLVED = "open", "solved"
    STATUS_CHOICES = [(OPEN, "Open"), (SOLVED, "Solved")]
    PRIORITY_CHOICES = [(1, "#1"), (2, "#2"), (3, "#3")]

    team = models.ForeignKey("core.Team", on_delete=models.CASCADE, related_name="issues")
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    horizon = models.CharField("List", max_length=5, choices=HORIZON_CHOICES, default=SHORT)
    status = models.CharField(max_length=6, choices=STATUS_CHOICES, default=OPEN)
    priority = models.PositiveSmallIntegerField(choices=PRIORITY_CHOICES, null=True, blank=True)
    resolution = models.TextField("Solution / notes", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    solved_at = models.DateTimeField(null=True, blank=True)
    solved_meeting = models.ForeignKey(
        "meetings.Meeting", null=True, blank=True, on_delete=models.SET_NULL, related_name="solved_issues"
    )
    raised_meeting = models.ForeignKey(
        "meetings.Meeting", null=True, blank=True, on_delete=models.SET_NULL, related_name="raised_issues"
    )
    source_measurable = models.ForeignKey(
        "scorecard.Measurable", null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    source_rock = models.ForeignKey(
        "rocks.Rock", null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    source_headline = models.ForeignKey(
        "meetings.Headline", null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )

    class Meta:
        ordering = ["status", models.F("priority").asc(nulls_last=True), "-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        return self.status == self.OPEN

    @property
    def source(self):
        return self.source_measurable or self.source_rock or self.source_headline

    def solve(self, meeting=None, resolution=None):
        self.status = self.SOLVED
        self.solved_at = timezone.now()
        self.priority = None
        if meeting is not None:
            self.solved_meeting = meeting
        if resolution:
            self.resolution = resolution
        self.save()

    def reopen(self):
        self.status = self.OPEN
        self.solved_at = None
        self.solved_meeting = None
        self.save()

    def set_priority(self, rank):
        """Rank 1-3 is unique per team list; the old holder of that rank is bumped off."""
        if rank:
            Issue.objects.filter(team=self.team, horizon=self.horizon, status=self.OPEN, priority=rank).exclude(
                pk=self.pk
            ).update(priority=None)
        self.priority = rank or None
        self.save(update_fields=["priority"])
