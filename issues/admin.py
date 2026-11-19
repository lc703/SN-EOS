from django.contrib import admin

from .models import Issue

admin.site.register(Issue, list_display=["title", "team", "owner", "horizon", "status", "priority"], list_filter=["team", "status", "horizon"], search_fields=["title"])
