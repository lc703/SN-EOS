import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

TOKEN_PREFIX = "sneos_"


def hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiToken(models.Model):
    """A personal API / MCP token. Acts as its owner, with the owner's permissions. Only a hash is stored."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField(max_length=80, help_text="Where it's used, e.g. 'Claude desktop'.")
    prefix = models.CharField(max_length=16, editable=False)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    can_write = models.BooleanField(default=True, help_text="Off = read-only.")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @property
    def is_active(self):
        return self.revoked_at is None and self.user.is_active

    @classmethod
    def issue(cls, user, name, can_write=True):
        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        token = cls.objects.create(
            user=user, name=name or "API token", prefix=raw[: len(TOKEN_PREFIX) + 6], key_hash=hash_token(raw), can_write=can_write
        )
        return token, raw

    @classmethod
    def authenticate(cls, raw):
        if not raw or not raw.startswith(TOKEN_PREFIX):
            return None
        token = cls.objects.select_related("user").filter(key_hash=hash_token(raw), revoked_at__isnull=True).first()
        if token is None or not token.user.is_active:
            return None
        now = timezone.now()
        if token.last_used_at is None or (now - token.last_used_at).total_seconds() > 60:
            cls.objects.filter(pk=token.pk).update(last_used_at=now)
        return token


class AuditLog(models.Model):
    WEB, API, MCP = "web", "api", "mcp"
    SOURCE_CHOICES = [(WEB, "Web"), (API, "REST API"), (MCP, "MCP")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    token = models.ForeignKey(ApiToken, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    source = models.CharField(max_length=4, choices=SOURCE_CHOICES)
    action = models.CharField(max_length=60)
    object_type = models.CharField(max_length=40, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.user} {self.action}"
