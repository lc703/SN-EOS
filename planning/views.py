from django.shortcuts import render

from core.utils import scope

from .models import Session


def sessions_list(request):
    team, quarter = scope(request)
    sessions = Session.objects.filter(team=team).select_related("quarter", "facilitator") if team else []
    return render(request, "planning/list.html", {"sessions": sessions})
