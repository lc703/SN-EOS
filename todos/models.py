import datetime as dt

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import LegacyMixin, monday_of


def default_due():
    return timezone.localdate() + dt.timedelta(days=7)


class TodoQuerySet(models.QuerySet):
    def visible_to(self, user):
        return self.filter(models.Q(is_private=False) | models.Q(owner=user) | models.Q(created_by=user))

    def team_todos(self):
        return self.filter(is_private=False)

    def due_in_week(self, monday):
        return self.filter(due_date__gte=monday, due_date__lt=monday + dt.timedelta(days=7))


class Todo(LegacyMixin):
    team = models.ForeignKey("core.Team", null=True, blank=True, on_delete=models.CASCADE, related_name="todos")
    is_private = models.BooleanField("Private", default=False, help_text="Only you can see a private to-do.")
    title = models.CharField(max_length=240)
    notes = models.TextField(blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="todos")
    due_date = models.DateField(default=default_due)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    rock = models.ForeignKey("rocks.Rock", null=True, blank=True, on_delete=models.SET_NULL, related_name="todos")
    issue = models.ForeignKey(
        "issues.Issue", null=True, blank=True, on_delete=models.SET_NULL, related_name="todos"
    )
    meeting = models.ForeignKey(
        "meetings.Meeting", null=True, blank=True, on_delete=models.SET_NULL, related_name="new_todos"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    asana_task_gid = models.CharField(max_length=40, blank=True)
    asana_sent_at = models.DateTimeField(null=True, blank=True)
    asana_completed_at = models.DateTimeField(null=True, blank=True)
    asana_unassigned = models.BooleanField(
        default=False, help_text="Sent before the owner was found in Asana, so the task has no assignee yet."
    )

    objects = TodoQuerySet.as_manager()

    class Meta:
        ordering = ["done", "due_date", "id"]

    def __str__(self):
        return self.title

    @property
    def overdue(self):
        return not self.done and self.due_date < timezone.localdate()

    @property
    def asana_state(self):
        if not self.asana_task_gid:
            return "none"
        return "done" if self.asana_completed_at and self.done else "sent"

    @property
    def asana_url(self):
        return f"https://app.asana.com/0/0/{self.asana_task_gid}" if self.asana_task_gid else ""

    def set_done(self, done):
        self.done = bool(done)
        self.done_at = timezone.now() if self.done else None
        self.save(update_fields=["done", "done_at"])


def completion(todos):
    """Percent of to-dos done (None when there are none)."""
    todos = list(todos)
    if not todos:
        return None
    return round(100 * sum(1 for t in todos if t.done) / len(todos))


def weekly_completion(qs, weeks=4, today=None):
    """[(monday, pct, done, total)] for the last `weeks` weeks, oldest first, by due date."""
    today = today or timezone.localdate()
    this_monday = monday_of(today)
    rows = []
    for i in range(weeks - 1, -1, -1):
        monday = this_monday - dt.timedelta(weeks=i)
        items = list(qs.due_in_week(monday))
        done = sum(1 for t in items if t.done)
        rows.append((monday, round(100 * done / len(items)) if items else None, done, len(items)))
    return rows
