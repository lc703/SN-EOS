from .base import *  # noqa: F401,F403
from .base import SECRET_KEY, env_bool

DEBUG = False
# Never enable quick login in prod, regardless of env vars.
DEV_LOGIN = False
TAILWIND_CDN = env_bool("TAILWIND_CDN", False)

if SECRET_KEY == "dev-insecure-change-me":
    raise RuntimeError("Set SECRET_KEY in production.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_CONTENT_TYPE_NOSNIFF = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
