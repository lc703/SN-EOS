import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

TOKEN_PREFIX = "sneos_"


class ApiToken(models.Model):
    """A personal token for the REST API and the MCP server. It acts as its owner, with their permissions.

    Only a SHA-256 hash is stored; the token itself is shown once, when it is created.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens")
    label = models.CharField(max_length=120)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    prefix = models.CharField(max_length=16, editable=False)
    can_write = models.BooleanField(default=True, help_text="Off = read only.")
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} ({self.prefix}…)"

    @staticmethod
    def hash(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, user, label, can_write=True, expires_at=None):
        """Returns (token, raw). Show `raw` once; it can't be recovered."""
        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        token = cls.objects.create(
            user=user, label=(label or "API token")[:120], token_hash=cls.hash(raw), prefix=raw[:12],
            can_write=can_write, expires_at=expires_at,
        )
        return token, raw

    @classmethod
    def find(cls, raw):
        if not raw or not raw.startswith(TOKEN_PREFIX):
            return None
        token = cls.objects.select_related("user").filter(token_hash=cls.hash(raw)).first()
        return token if token and token.is_live else None

    @property
    def is_live(self):
        if self.revoked_at or not self.user.is_active:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    @property
    def scope_label(self):
        return "Read & write" if self.can_write else "Read only"


class AuditLog(models.Model):
    """Every API and MCP request made with a token: who, what, and whether it worked."""

    REST, MCP = "rest", "mcp"
    CHANNEL_CHOICES = [(REST, "REST"), (MCP, "MCP")]

    token = models.ForeignKey(ApiToken, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="api_logs")
    channel = models.CharField(max_length=4, choices=CHANNEL_CHOICES)
    action = models.CharField(max_length=80, help_text="HTTP method + path, or the MCP tool name.")
    is_write = models.BooleanField(default=False)
    object_type = models.CharField(max_length=40, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    ok = models.BooleanField(default=True)
    status = models.PositiveSmallIntegerField(default=200)
    message = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.user} {self.action}"
