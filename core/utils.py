from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .context import current_quarter, current_team


def scope(request):
    """(team, quarter) for this request, cached so the context processor reuses them."""
    if not hasattr(request, "_team"):
        request._team = current_team(request)
        request._quarter = current_quarter(request)
    return request._team, request._quarter


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def go_back(request, default="/"):
    target = request.POST.get("next") or request.GET.get("next") or request.META.get("HTTP_REFERER")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect(default)


def require(allowed):
    if not allowed:
        raise PermissionDenied("You can't change this.")
