import os
from urllib.parse import unquote, urlparse

from .base import *  # noqa: F403


DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    *INSTALLED_APPS,
    "apps.core",
    "apps.assets",
    "apps.inspections",
    "apps.risks",
    "apps.capabilities",
    "apps.investigations",
    "apps.learning",
    "apps.audits",
]

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://inspection:inspection_dev@127.0.0.1:5432/inspection",
)
database_url = urlparse(DATABASE_URL)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": database_url.path.lstrip("/"),
        "USER": unquote(database_url.username or ""),
        "PASSWORD": unquote(database_url.password or ""),
        "HOST": database_url.hostname or "",
        "PORT": str(database_url.port or ""),
    }
}
