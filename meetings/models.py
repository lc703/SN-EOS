from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import LegacyMixin


SECTIONS = [
    ("segue", "Segue"),
    ("scorecard", "Scorecard"),
    ("rocks", "Rock Review"),
    ("headlines", "Headlines"),
    ("todos", "To-Do List"),
    ("ids", "IDS"),
    ("conclude", "Conclude"),
]
SECTION_KEYS = [k for k, _ in SECTIONS]


class Meeting(LegacyMixin):
    team = models.ForeignKey("core.Team", on_delete=models.CASCADE, related_name="meetings")
    quarter = models.ForeignKey("core.Quarter", null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateField(default=timezone.localdate)
    facilitator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    attendees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="meetings")
    current_section = models.CharField(max_length=12, choices=SECTIONS, default="segue")
    segue_notes = models.TextField("Segue / good news", blank=True)
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    concluded_at = models.DateTimeField(null=True, blank=True)
    recap_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.team} L10 {self.date:%b %-d, %Y}"

    @property
    def is_concluded(self):
        return self.concluded_at is not None

    @property
    def average_rating(self):
        scores = [r.rating for r in self.ratings.all() if r.rating]
        if not scores:
            return None
        return round(sum(scores) / len(scores), 1)


class Headline(LegacyMixin):
    CUSTOMER, EMPLOYEE = "customer", "employee"
    KIND_CHOICES = [(CUSTOMER, "Customer"), (EMPLOYEE, "Employee")]

    team = models.ForeignKey("core.Team", on_delete=models.CASCADE, related_name="headlines")
    meeting = models.ForeignKey(Meeting, null=True, blank=True, on_delete=models.SET_NULL, related_name="headlines")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=CUSTOMER)
    text = models.CharField(max_length=300)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.text


class CascadingMessage(models.Model):
    """Conclude: what to tell the rest of the company. Shows in the recipients' next L10 headlines."""

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="cascades")
    text = models.TextField()
    to_teams = models.ManyToManyField("core.Team", blank=True, related_name="cascades_received")
    to_everyone = models.BooleanField(default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.text[:60]


class MeetingRating(LegacyMixin):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    rating = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("meeting", "user")]
        ordering = ["user__name"]

    def __str__(self):
        return f"{self.user}: {self.rating}"
