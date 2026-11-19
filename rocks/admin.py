from django.contrib import admin

from .models import Milestone, Rock, RockUpdate


class MilestoneInline(admin.TabularInline):
    model = Milestone
    extra = 0


class RockUpdateInline(admin.TabularInline):
    model = RockUpdate
    extra = 0
    fields = ["week_start", "color", "note", "recovery_plan", "author"]


@admin.register(Rock)
class RockAdmin(admin.ModelAdmin):
    list_display = ["title", "team", "quarter", "owner", "status", "is_company"]
    list_filter = ["quarter", "team", "status"]
    inlines = [MilestoneInline, RockUpdateInline]
