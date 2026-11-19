from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import LegacyMixin

QUARTERLY, ANNUAL = "quarterly", "annual"
KIND_CHOICES = [(QUARTERLY, "Quarterly Planning"), (ANNUAL, "Annual Planning")]

# EOS session agendas (Traction / EOS Worldwide). Each entry: key, title, prompt.
AGENDAS = {
    QUARTERLY: [
        ("segue", "Segue", "Best business and personal news from the last 90 days, what's working and not working, and expectations for today."),
        ("review", "Review previous quarter", "Revenue, profit and the scorecard. Which rocks got done? Lessons learned."),
        ("vto", "Review the V/TO", "Read it aloud. Is everyone still on the same page? Add anything to the Issues List."),
        ("rocks", "Establish next quarter's Rocks", "Three to seven company rocks first, then everyone's individual rocks. SMART, one owner each."),
        ("ids", "Tackle key issues", "IDS the Issues List: prioritize the top three, solve them for good."),
        ("next_steps", "Next steps", "Who does what by when, and what gets cascaded to the rest of the company."),
        ("conclude", "Conclude", "Feedback on the session, were expectations met, and a 1-10 rating."),
    ],
    ANNUAL: [
        ("segue", "Segue", "Best business and personal news of the year, what's working and not working, and expectations."),
        ("review", "Review previous year", "Last year's goals, numbers and rocks. Lessons learned."),
        ("team_health", "Team health building", "Each person: the one thing everyone else does well, and the one thing they should work on."),
        ("swot", "SWOT / Issues List", "Strengths, weaknesses, opportunities and threats. Anything that needs solving goes on the Issues List."),
        ("vto", "V/TO through the 3-year picture", "Core values, core focus, 10-year target, marketing strategy and the 3-year picture."),
        ("one_year", "Establish the 1-year plan", "Revenue, profit, measurables and three to seven goals for the year."),
        ("rocks", "Establish next quarter's Rocks", "Company rocks first, then individual rocks."),
        ("ids", "Tackle key issues", "IDS the most important issues for the year."),
        ("next_steps", "Next steps", "Who does what by when, and what gets cascaded."),
        ("conclude", "Conclude", "Feedback, were expectations met, and a 1-10 rating."),
    ],
}

ITEM_KINDS = [
    ("best_news", "Best news"),
    ("working", "What's working"),
    ("not_working", "What's not working"),
    ("expectation", "Expectation"),
    ("lesson", "Lesson learned"),
    ("strength", "Strength"),
    ("weakness", "Weakness"),
    ("opportunity", "Opportunity"),
    ("threat", "Threat"),
    ("does_well", "Does well"),
    ("work_on", "Should work on"),
    ("vto_check", "V/TO check"),
    ("priority", "Priority"),
    ("next_step", "Next step"),
    ("cascade", "Cascading message"),
    ("feedback", "Feedback"),
    ("note", "Note"),
]

# Which item kinds each section collects, in display order.
SECTION_KINDS = {
    "segue": ["best_news", "working", "not_working", "expectation"],
    "review": ["lesson", "note"],
    "team_health": ["does_well", "work_on"],
    "swot": ["strength", "weakness", "opportunity", "threat"],
    "vto": ["vto_check"],
    "one_year": ["note"],
    "rocks": ["note"],
    "ids": ["priority"],
    "next_steps": ["next_step", "cascade"],
    "conclude": ["feedback"],
}


class Session(LegacyMixin):
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=QUARTERLY)
    team = models.ForeignKey("core.Team", on_delete=models.CASCADE, related_name="planning_sessions")
    quarter = models.ForeignKey(
        "core.Quarter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="The quarter being reviewed.",
    )
    next_quarter = models.ForeignKey(
        "core.Quarter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="The quarter whose rocks get set in this session.",
    )
    date = models.DateField(default=timezone.localdate)
    facilitator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    attendees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="planning_sessions")
    current_section = models.CharField(max_length=16, default="segue")
    section_notes = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    concluded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.team} {self.get_kind_display()} {self.date:%b %-d, %Y}"

    @property
    def agenda(self):
        return AGENDAS[self.kind]

    @property
    def section_keys(self):
        return [k for k, _, _ in self.agenda]

    @property
    def is_concluded(self):
        return self.concluded_at is not None

    @property
    def average_rating(self):
        scores = [r.rating for r in self.ratings.all() if r.rating]
        return round(sum(scores) / len(scores), 1) if scores else None


class SessionItem(models.Model):
    GREEN, YELLOW, RED = "green", "yellow", "red"
    COLOR_CHOICES = [(GREEN, "Green"), (YELLOW, "Yellow"), (RED, "Red")]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="items")
    section = models.CharField(max_length=16)
    kind = models.CharField(max_length=16, choices=ITEM_KINDS)
    text = models.TextField()
    color = models.CharField(max_length=6, choices=COLOR_CHOICES, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    about = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Team health: who the feedback is for.",
    )
    sort = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    legacy_key = models.CharField(max_length=60, null=True, blank=True, unique=True, editable=False)
    legacy = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        ordering = ["sort", "created_at", "id"]

    def __str__(self):
        return self.text[:60]


class SessionRating(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    rating = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("session", "user")]
        ordering = ["user__name"]
