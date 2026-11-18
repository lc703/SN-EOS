import os

import dj_database_url

from .base import *  # noqa: F401,F403

DEBUG = False
DEV_LOGIN = True
TAILWIND_CDN = True
SECRET_KEY = "test"
ALLOWED_HOSTS = ["*"]
# Set TEST_DATABASE_URL to run the suite against Postgres; default is in-memory SQLite.
DATABASES = {
    "default": dj_database_url.parse(os.environ["TEST_DATABASE_URL"])
    if os.environ.get("TEST_DATABASE_URL")
    else {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
ALLOWED_EMAIL_DOMAIN = "steuartnutrition.com"
