from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import LegacyRecord, Quarter, Team, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["email", "name", "role", "home_team", "is_active"]
    list_filter = ["role", "is_active", "teams"]
    search_fields = ["email", "name"]
    ordering = ["name"]
    fieldsets = [
        (None, {"fields": ["email", "username", "name", "title", "role", "home_team", "asana_email", "is_active"]}),
        ("Django admin", {"fields": ["is_staff", "is_superuser", "groups"], "classes": ["collapse"]}),
    ]
    add_fieldsets = [(None, {"fields": ["email", "username", "name", "role"]})]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "short_code", "is_leadership", "sort"]
    filter_horizontal = ["members"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Quarter)
class QuarterAdmin(admin.ModelAdmin):
    list_display = ["name", "start_date", "end_date", "is_current"]


@admin.register(LegacyRecord)
class LegacyRecordAdmin(admin.ModelAdmin):
    list_display = ["model", "legacy_id", "imported_at"]
    list_filter = ["model"]
