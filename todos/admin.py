from django.contrib import admin

from .models import Todo

admin.site.register(Todo, list_display=["title", "team", "owner", "due_date", "done", "is_private"], list_filter=["team", "done"], search_fields=["title"])
