from django.contrib import admin

from .models import Headline, Meeting, MeetingRating


class RatingInline(admin.TabularInline):
    model = MeetingRating
    extra = 0


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ["team", "date", "concluded_at"]
    list_filter = ["team"]
    inlines = [RatingInline]


admin.site.register(Headline, list_display=["text", "team", "kind", "created_at"])
