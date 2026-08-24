from django.urls import path

from . import public_views


urlpatterns = [
    path("<uuid:investigation_id>", public_views.detail, name="investigation-detail-no-slash"),
    path("<uuid:investigation_id>/", public_views.detail, name="investigation-detail"),
    path(
        "<uuid:investigation_id>/events",
        public_views.events,
        name="investigation-events-no-slash",
    ),
    path(
        "<uuid:investigation_id>/events/",
        public_views.events,
        name="investigation-events",
    ),
    path(
        "<uuid:investigation_id>/tool-calls",
        public_views.tool_calls,
        name="investigation-tool-calls-no-slash",
    ),
    path(
        "<uuid:investigation_id>/tool-calls/",
        public_views.tool_calls,
        name="investigation-tool-calls",
    ),
    path(
        "<uuid:investigation_id>/cancel",
        public_views.cancel,
        name="investigation-cancel-no-slash",
    ),
    path(
        "<uuid:investigation_id>/cancel/",
        public_views.cancel,
        name="investigation-cancel",
    ),
]
