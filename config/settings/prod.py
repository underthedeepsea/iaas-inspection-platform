"""Production defaults; durable workers must be configured separately."""

import os

from .dev import *  # noqa: F403


DEBUG = False
BACKGROUND_TASK_PROVIDER = os.getenv("BACKGROUND_TASK_PROVIDER", "airflow")
LOCAL_BACKGROUND_WORKER_ENABLED = False
