"""Production defaults; durable workers must be configured separately."""

from .dev import *  # noqa: F403


DEBUG = False
LOCAL_BACKGROUND_WORKER_ENABLED = False
