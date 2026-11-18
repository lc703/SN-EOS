from django.conf import settings
from django.shortcuts import redirect

PUBLIC_PREFIXES = ("/accounts/", "/healthz", "/dev-login", "/static/", "/favicon")


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(PUBLIC_PREFIXES):
            return redirect(f"{settings.LOGIN_URL}?next={request.get_full_path()}")
        return self.get_response(request)
