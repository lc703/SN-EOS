from django.conf import settings

from django.utils import timezone

from .context import current_quarter, current_team
from .models import Quarter, Team, monday_of

SHORTCUTS = [
    (["G", "H"], "My 90 (home)"),
    (["G", "S"], "Scorecard"),
    (["G", "R"], "Rocks"),
    (["G", "T"], "To-Dos"),
    (["G", "I"], "Issues"),
    (["G", "L"], "Level 10 meetings"),
    (["G", "Q"], "Quarterly & annual sessions"),
    (["G", "V"], "V/TO"),
    (["G", "C"], "Accountability Chart"),
    (["G", "P"], "People & 1:1s"),
    (["N"], "New item on this page"),
    (["/"], "Focus the first search or input"),
    (["←", "→", "↑", "↓"], "Move between Scorecard cells"),
    (["Enter"], "Edit the selected cell"),
    (["[", "]"], "L10 and sessions: previous / next section"),
    (["+", "−", "0"], "Chart: zoom in, out, fit"),
    (["Esc"], "Close panel or dialog"),
    (["?"], "Show this help"),
]

MOBILE_NAV = [
    ("/", "Home", "home", "/"),
    ("/scorecard/", "Scorecard", "scorecard", "/scorecard"),
    ("/rocks/", "Rocks", "rocks", "/rocks"),
    ("/todos/", "To-Dos", "todos", "/todos"),
    ("/meetings/", "L10", "l10", "/meetings"),
]


def app(request):
    ctx = {
        "APP_NAME": settings.APP_NAME,
        "COMPANY_NAME": settings.COMPANY_NAME,
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
            shortcuts=SHORTCUTS,
            mobile_nav=MOBILE_NAV,
            this_monday=monday_of(timezone.localdate()),
        )
    return ctx
