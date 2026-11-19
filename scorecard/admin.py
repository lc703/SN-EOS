from django.contrib import admin

from .models import Measurable, Plant, ScoreEntry

admin.site.register(Plant, list_display=["name", "slug", "sort"])
admin.site.register(
    Measurable, list_display=["title", "plant", "team", "owner", "unit", "goal_compare", "goal"], list_filter=["plant", "team"]
)
admin.site.register(ScoreEntry, list_display=["measurable", "week_start", "value"])
