from django.contrib import admin

from .models import ApiToken, AuditLog


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("label", "user", "prefix", "can_write", "created_at", "last_used_at", "expires_at", "revoked_at")
    list_filter = ("can_write",)
    search_fields = ("label", "user__email", "prefix")
    readonly_fields = ("token_hash", "prefix", "created_at", "last_used_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("at", "user", "channel", "action", "object_type", "object_id", "is_write", "ok", "status")
    list_filter = ("channel", "is_write", "ok")
    search_fields = ("action", "user__email", "object_type", "object_id", "message")
    date_hierarchy = "at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
