from django.contrib import admin

from .models import Milestone, Rock


class MilestoneInline(admin.TabularInline):
    model = Milestone
    extra = 0


@admin.register(Rock)
class RockAdmin(admin.ModelAdmin):
    list_display = ["title", "team", "quarter", "owner", "status", "is_company"]
    list_filter = ["quarter", "team", "status"]
    inlines = [MilestoneInline]
