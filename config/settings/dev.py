import os
from urllib.parse import unquote, urlparse

from .base import *  # noqa: F403


DEBUG = True
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "fake")
BACKGROUND_TASK_PROVIDER = os.getenv("BACKGROUND_TASK_PROVIDER", "local")
AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL")
AIRFLOW_USERNAME = os.getenv("AIRFLOW_USERNAME")
AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD")
AIRFLOW_MANUAL_INSPECTION_DAG_ID = os.getenv("AIRFLOW_MANUAL_INSPECTION_DAG_ID")
AIRFLOW_RESOURCE_INVESTIGATION_DAG_ID = os.getenv(
    "AIRFLOW_RESOURCE_INVESTIGATION_DAG_ID"
)
LOCAL_BACKGROUND_WORKER_ENABLED = os.getenv("LOCAL_BACKGROUND_WORKER_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.postgres",
    "django.contrib.staticfiles",
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

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
