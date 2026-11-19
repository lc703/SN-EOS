import datetime as dt

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import LegacyMixin, monday_of

GREEN, YELLOW, RED = "green", "yellow", "red"
RAG_CHOICES = [(GREEN, "Green"), (YELLOW, "Yellow"), (RED, "Red")]


class Rock(LegacyMixin):
    ON_TRACK, OFF_TRACK, DONE = "on_track", "off_track", "done"
    STATUS_CHOICES = [(ON_TRACK, "On Track"), (OFF_TRACK, "Off Track"), (DONE, "Done")]

    quarter = models.ForeignKey("core.Quarter", on_delete=models.CASCADE, related_name="rocks")
    team = models.ForeignKey("core.Team", on_delete=models.CASCADE, related_name="rocks")
    is_company = models.BooleanField(
        "Company rock", default=False, help_text="Company rocks show for every team. Leave off for a departmental rock."
    )
    goal = models.ForeignKey(
        "vision.Goal", null=True, blank=True, on_delete=models.SET_NULL, related_name="rocks",
        verbose_name="1-year goal", help_text="The V/TO 1-year goal this rock moves forward.",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="rocks"
    )
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ON_TRACK)
    sort = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_company", "sort", "id"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.due_date and self.quarter_id:
            self.due_date = self.quarter.end_date
        super().save(*args, **kwargs)

    @property
    def kind_label(self):
        return "Company" if self.is_company else "Departmental"

    @property
    def milestone_progress(self):
        ms = list(self.milestones.all())
        if not ms:
            return None
        return sum(1 for m in ms if m.done), len(ms)

    @property
    def milestone_pct(self):
        p = self.milestone_progress
        return round(100 * p[0] / p[1]) if p else None

    def latest_update(self):
        ups = list(self.updates.all())
        return max(ups, key=lambda u: u.week_start) if ups else None

    @property
    def rag(self):
        """Latest weekly G/Y/R, falling back to the On/Off Track status."""
        if self.status == self.DONE:
            return "done"
        latest = self.latest_update()
        if latest:
            return latest.rag
        return RED if self.status == self.OFF_TRACK else GREEN

    def week_strip(self):
        """[(monday, update-or-None, is_future)] for the 13 weeks of the rock's quarter."""
        by_week = {u.week_start: u for u in self.updates.all()}
        this_monday = monday_of(timezone.localdate())
        return [(w, by_week.get(w), w > this_monday) for w in self.quarter.weeks()]

    def needs_update_this_week(self):
        if self.status == self.DONE:
            return False
        this_monday = monday_of(timezone.localdate())
        return not any(u.week_start == this_monday for u in self.updates.all())


class RockUpdate(LegacyMixin):
    """The owner's weekly G/Y/R call on a rock, with a note. Red needs a recovery plan."""

    rock = models.ForeignKey(Rock, on_delete=models.CASCADE, related_name="updates")
    week_start = models.DateField()
    rag = models.CharField("Status", max_length=6, choices=RAG_CHOICES)
    note = models.TextField(blank=True)
    recovery_plan = models.TextField(blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-week_start"]
        constraints = [models.UniqueConstraint(fields=["rock", "week_start"], name="uniq_rock_update_week")]

    def __str__(self):
        return f"{self.rock} {self.week_start} {self.rag}"

    def clean(self):
        if self.rag == RED and not (self.recovery_plan or "").strip():
            raise ValidationError({"recovery_plan": "A red rock needs a recovery plan."})

    def save(self, *args, sync=True, **kwargs):
        if isinstance(self.week_start, dt.datetime):
            self.week_start = self.week_start.date()
        self.week_start = monday_of(self.week_start)
        super().save(*args, **kwargs)
        if sync:
            self.sync_rock()

    def sync_rock(self):
        """The newest update drives On/Off Track, unless the rock is Done."""
        rock = self.rock
        latest = rock.updates.order_by("-week_start").first()
        if latest and latest.pk == self.pk and rock.status != Rock.DONE:
            status = Rock.OFF_TRACK if self.rag == RED else Rock.ON_TRACK
            if rock.status != status:
                Rock.objects.filter(pk=rock.pk).update(status=status, updated_at=timezone.now())
                rock.status = status


class Milestone(LegacyMixin):
    rock = models.ForeignKey(Rock, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="milestones"
    )
    due_date = models.DateField(null=True, blank=True)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "due_date", "id"]

    def __str__(self):
        return self.title

    @property
    def overdue(self):
        return bool(self.due_date and not self.done and self.due_date < timezone.localdate())

    def set_done(self, done):
        self.done = bool(done)
        self.done_at = timezone.now() if self.done else None
        self.save(update_fields=["done", "done_at"])
