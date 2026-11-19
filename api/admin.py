from django.contrib import admin

from .models import ApiToken, AuditLog


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "prefix", "can_write", "created_at", "last_used_at", "revoked_at"]
    readonly_fields = ["prefix", "key_hash", "created_at", "last_used_at"]
    list_filter = ["can_write"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "user", "source", "action", "object_type", "object_id", "summary"]
    list_filter = ["source", "action"]
    readonly_fields = [f for f in ["user", "token", "source", "action", "object_type", "object_id", "summary", "data", "created_at"]]

    def has_add_permission(self, request):
        return False
