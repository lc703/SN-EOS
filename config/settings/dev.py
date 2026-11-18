from .base import *  # noqa: F401,F403
from .base import env, env_bool

DEBUG = True
ALLOWED_HOSTS = ["*"]
DEV_LOGIN = env_bool("DEV_LOGIN", True)
TAILWIND_CDN = True
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
