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


def stash_form_errors(request, key, form, keep=("title",)):
    """Remember why a quick-add form was refused, plus what was typed, for the form to show after the redirect.

    The add forms live inside other pages (an L10 section, a list), so the refusal is redirected back to
    that page; `{% form_errors key as fe %}` pops this and renders the reasons next to the form itself.
    """
    errors = []
    for name, msgs in form.errors.items():
        label = "" if name == "__all__" else str(form[name].label or name)
        errors.extend([label, str(m)] for m in msgs)
    request.session[f"form_errors:{key}"] = {"errors": errors, "values": {k: request.POST.get(k, "") for k in keep}}
