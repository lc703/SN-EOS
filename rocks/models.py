from django.conf import settings
from django.db import models

from core.models import LegacyMixin


class Rock(LegacyMixin):
    ON_TRACK, OFF_TRACK, DONE = "on_track", "off_track", "done"
    STATUS_CHOICES = [(ON_TRACK, "On Track"), (OFF_TRACK, "Off Track"), (DONE, "Done")]

    quarter = models.ForeignKey("core.Quarter", on_delete=models.CASCADE, related_name="rocks")
    team = models.ForeignKey("core.Team", on_delete=models.CASCADE, related_name="rocks")
    is_company = models.BooleanField(
        "Company rock", default=False, help_text="Company rocks show for every team. Leave off for a team rock."
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
    def milestone_progress(self):
        ms = list(self.milestones.all())
        if not ms:
            return None
        return sum(1 for m in ms if m.done), len(ms)


class Milestone(LegacyMixin):
    rock = models.ForeignKey(Rock, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=200)
    due_date = models.DateField(null=True, blank=True)
    done = models.BooleanField(default=False)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["due_date", "sort", "id"]

    def __str__(self):
        return self.title
