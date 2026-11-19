from django.conf import settings

from .context import current_quarter, current_team
from .models import Quarter, Team


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
    return ctx
