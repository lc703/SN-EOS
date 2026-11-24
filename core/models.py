import datetime as dt

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def monday_of(day):
    return day - dt.timedelta(days=day.weekday())


class LegacyMixin(models.Model):
    """Rows imported from the Battle Planner keep their old pk and anything we could not map."""

    legacy_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    legacy = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        abstract = True


class AppUserManager(UserManager):
    def create_user(self, email=None, password=None, **extra):
        extra.setdefault("username", (email or "").lower())
        return super().create_user(extra.pop("username"), email=(email or "").lower(), password=password, **extra)

    def create_superuser(self, username=None, email=None, password=None, **extra):
        email = (email or username or "").lower()
        extra.setdefault("role", User.ROLE_ADMIN)
        return super().create_superuser(email, email=email, password=password, **extra)


class User(AbstractUser):
    ROLE_ADMIN = "admin"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [(ROLE_ADMIN, "Admin"), (ROLE_MEMBER, "Member")]

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=120, blank=True)
    title = models.CharField(max_length=120, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    home_team = models.ForeignKey(
        "core.Team", null=True, blank=True, on_delete=models.SET_NULL, related_name="home_users"
    )
    asana_email = models.EmailField(
        "Asana email", blank=True, help_text="Only if this person's Asana login differs from their work email."
    )
    legacy_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    legacy = models.JSONField(default=dict, blank=True, editable=False)

    objects = AppUserManager()

    REQUIRED_FIELDS = ["email"]

    class Meta:
        ordering = ["name", "email"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.name or self.get_full_name() or self.email.split("@")[0]

    @property
    def first(self):
        return self.display_name.split(" ")[0]

    @property
    def initials(self):
        parts = [p for p in self.display_name.replace("-", " ").split(" ") if p]
        return "".join(p[0] for p in parts[:2]).upper()

    @property
    def is_admin(self):
        return self.is_superuser or self.role == self.ROLE_ADMIN

    @property
    def can_sign_in(self):
        from django.conf import settings

        return self.email.lower().endswith("@" + settings.ALLOWED_EMAIL_DOMAIN)

    def save(self, *args, **kwargs):
        self.email = (self.email or "").lower()
        if not self.username:
            self.username = self.email
        if self.role == self.ROLE_ADMIN:
            self.is_staff = True
            self.is_superuser = True
        super().save(*args, **kwargs)


class Team(LegacyMixin):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    short_code = models.CharField(max_length=6, blank=True)
    is_leadership = models.BooleanField(
        default=False, help_text="The company leadership team. Its rocks are company rocks."
    )
    sort = models.PositiveIntegerField(default=0)
    members = models.ManyToManyField(User, blank=True, related_name="teams")

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name

    @property
    def label(self):
        return f"{self.name} (Leadership)" if self.is_leadership else self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class QuarterQuerySet(models.QuerySet):
    def for_date(self, day):
        return self.filter(start_date__lte=day, end_date__gte=day).first()

    def current(self):
        today = timezone.localdate()
        return self.for_date(today) or self.filter(is_current=True).first() or self.order_by("-start_date").first()


class Quarter(LegacyMixin):
    name = models.CharField(max_length=40, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    objects = QuarterQuerySet.as_manager()

    WEEKS = 13

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.name

    def weeks(self):
        """The 13 scorecard weeks: Mondays starting with the week the quarter begins in."""
        first = monday_of(self.start_date)
        return [first + dt.timedelta(weeks=i) for i in range(self.WEEKS)]

    def contains(self, day):
        return self.start_date <= day <= self.end_date

    @classmethod
    def for_calendar(cls, day):
        q = (day.month - 1) // 3 + 1
        start = dt.date(day.year, 3 * (q - 1) + 1, 1)
        end_month = 3 * q
        end = (dt.date(day.year + (end_month == 12), end_month % 12 + 1, 1)) - dt.timedelta(days=1)
        obj, _ = cls.objects.get_or_create(
            name=f"Q{q} {day.year}", defaults={"start_date": start, "end_date": end}
        )
        return obj


class AppSetting(models.Model):
    """Small key/value store. The Asana integration keeps the project, section and user ids it looked up here."""

    key = models.CharField(max_length=120, primary_key=True)
    value = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key

    @classmethod
    def get(cls, key, default=""):
        row = cls.objects.filter(pk=key).first()
        return row.value if row else default

    @classmethod
    def put(cls, key, value):
        cls.objects.update_or_create(pk=key, defaults={"value": value})


class LegacyRecord(models.Model):
    """Raw Battle Planner rows that have no home in EOS (offsites, SWOT, 4 Whats, ...)."""

    model = models.CharField(max_length=80)
    legacy_id = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("model", "legacy_id")]
        ordering = ["model", "legacy_id"]

    def __str__(self):
        return f"{self.model}#{self.legacy_id}"
