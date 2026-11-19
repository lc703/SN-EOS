from django.contrib import admin

from .models import VTO, CoreProcess, CoreValue, Seat

admin.site.register(CoreValue, list_display=["name", "sort", "active"])
admin.site.register(VTO)
admin.site.register(Seat, list_display=["title", "person", "person_name", "status", "agency", "team", "parent"], list_filter=["team", "status", "agency"])
admin.site.register(CoreProcess, list_display=["name", "owner", "documented", "followed_by_all", "sort"])
