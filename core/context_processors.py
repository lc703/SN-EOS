from django.conf import settings
from django.urls import reverse

from .context import current_quarter, current_team
from .models import Quarter, Team, User


def app(request):
    ctx = {
        "APP_NAME": settings.APP_NAME,
        "COMPANY_NAME": settings.COMPANY_NAME,
        "TAILWIND_CDN": settings.TAILWIND_CDN,
        "DEV_LOGIN": settings.DEV_LOGIN,
        "STAGING_PASSWORD_LOGIN": settings.STAGING_PASSWORD_LOGIN,
        "ALLOWED_EMAIL_DOMAIN": settings.ALLOWED_EMAIL_DOMAIN,
    }
    if getattr(request, "user", None) and request.user.is_authenticated:
        ctx.update(
            all_teams=Team.objects.all(),
            all_quarters=Quarter.objects.all(),
            team=getattr(request, "_team", None) or current_team(request),
            quarter=getattr(request, "_quarter", None) or current_quarter(request),
            is_admin=request.user.is_admin,
        )
        ctx["sn_nav"] = nav_data(ctx["all_teams"], request.user)
    return ctx


SHORTCUTS = [
    ("h", "home", "My 90"),
    ("s", "scorecard", "Scorecard"),
    ("r", "rocks", "Rocks"),
    ("i", "issues", "Issues"),
    ("t", "todos", "To-Dos"),
    ("l", "meetings", "Level 10 Meetings"),
    ("q", "planning", "Quarterly & Annual Planning"),
    ("v", "vto", "V/TO"),
    ("c", "chart", "Accountability Chart"),
    ("p", "people", "People"),
    ("o", "conversations", "Quarterly Conversations"),
]


def nav_data(teams, user=None):
    nav = {key: reverse(name) for key, name, _ in SHORTCUTS}
    palette = [{"label": label, "url": reverse(name), "group": "Go to", "hint": f"g {key}"} for key, name, label in SHORTCUTS]
    palette += [
        {"label": "New issue", "url": reverse("issues") + "#add", "group": "Create", "keywords": "ids add"},
        {"label": "New to-do", "url": reverse("todos") + "#add", "group": "Create", "keywords": "task add"},
        {"label": "New rock", "url": reverse("rock_new"), "group": "Create", "keywords": "quarterly priority"},
        {"label": "New measurable", "url": reverse("measurable_new"), "group": "Create", "keywords": "scorecard kpi"},
        {"label": "Start Level 10 meeting", "url": reverse("meetings"), "group": "Create", "keywords": "l10 weekly"},
        {"label": "Core Processes", "url": reverse("vto") + "#processes", "group": "Go to", "keywords": "process fba"},
        {"label": "API tokens & AI connections", "url": reverse("api_tokens"), "group": "Settings", "keywords": "mcp claude integrations"},
    ]
    palette += [{"label": f"Switch to {t.name}", "url": f"?team={t.slug}", "group": "Team"} for t in teams]
    if user is not None and getattr(user, "is_authenticated", False):
        for person in User.objects.filter(is_active=True).order_by("name", "id"):
            mine = person.pk == user.pk
            palette.append({
                "label": "My dashboard" if mine else f"{person.display_name}'s dashboard",
                "url": reverse("home") if mine else reverse("person_dashboard", args=[person.pk]),
                "group": "People",
                "keywords": f"{person.display_name} {person.email} dashboard 90",
            })
    return {"nav": nav, "palette": palette, "shortcuts": [{"key": f"g {k}", "label": label} for k, _, label in SHORTCUTS]}
