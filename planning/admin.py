from django.contrib import admin

from .models import Session, SessionItem, SessionRating


class ItemInline(admin.TabularInline):
    model = SessionItem
    extra = 0
    fields = ["section", "kind", "text", "color", "author", "about"]


class RatingInline(admin.TabularInline):
    model = SessionRating
    extra = 0


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ["team", "kind", "date", "quarter", "facilitator", "concluded_at"]
    list_filter = ["kind", "team"]
    inlines = [ItemInline, RatingInline]
