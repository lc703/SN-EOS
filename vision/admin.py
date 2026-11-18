from django.contrib import admin

from .models import VTO, CoreValue, Seat

admin.site.register(CoreValue, list_display=["name", "sort", "active"])
admin.site.register(VTO)
admin.site.register(Seat, list_display=["title", "person", "person_name", "team", "parent"], list_filter=["team"])
