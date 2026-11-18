from django.contrib import admin

from .models import Measurable, ScoreEntry

admin.site.register(Measurable, list_display=["title", "team", "owner", "unit", "goal_compare", "goal"], list_filter=["team"])
admin.site.register(ScoreEntry, list_display=["measurable", "week_start", "value"])
