from django.urls import path

from . import api
from apps.investigations import api as investigation_api
from apps.investigations import public_views as investigation_public_views


urlpatterns = [
    path("resource-types", api.resource_types, name="resource-types"),
    path("resource-types/", api.resource_types, name="resource-types-slash"),
    path(
        "resource-types/<str:resource_type_code>/overview",
        api.resource_overview,
        name="resource-type-overview",
    ),
    path(
        "resource-types/<str:resource_type_code>/overview/",
        api.resource_overview,
        name="resource-type-overview-slash",
    ),
    path(
        "resource-types/<str:resource_type_code>/inspection-history",
        api.resource_history,
        name="resource-type-history",
    ),
    path(
        "resource-types/<str:resource_type_code>/inspection-history/",
        api.resource_history,
        name="resource-type-history-slash",
    ),
    path(
        "resource-types/<str:resource_type_code>/risks",
        api.resource_risks,
        name="resource-type-risks",
    ),
    path(
        "resource-types/<str:resource_type_code>/risks/",
        api.resource_risks,
        name="resource-type-risks-slash",
    ),
    path(
        "resource-types/<str:resource_type_code>/inspection-history/<uuid:run_id>",
        api.resource_run_detail,
        name="resource-type-run-detail",
    ),
    path(
        "resource-types/<str:resource_type_code>/inspection-history/<uuid:run_id>/",
        api.resource_run_detail,
        name="resource-type-run-detail-slash",
    ),
    path(
        "inspection-runs/<uuid:run_id>/events",
        api.inspection_run_events,
        name="inspection-run-events",
    ),
    path(
        "inspection-runs/<uuid:run_id>/events/",
        api.inspection_run_events,
        name="inspection-run-events-slash",
    ),
    path(
        "resource-types/<str:resource_type_code>/investigations",
        investigation_api.resource_investigation_collection,
        name="resource-investigation-collection",
    ),
    path(
        "resource-types/<str:resource_type_code>/investigations/",
        investigation_api.resource_investigation_collection,
        name="resource-investigation-collection-slash",
    ),
    path(
        "investigations/<uuid:investigation_id>/events/stream",
        investigation_api.investigation_event_stream,
        name="resource-investigation-event-stream",
    ),
    path(
        "investigations/<uuid:investigation_id>/events/stream/",
        investigation_api.investigation_event_stream,
        name="resource-investigation-event-stream-slash",
    ),
    path(
        "investigations/<uuid:investigation_id>/events",
        investigation_public_views.events,
        name="resource-investigation-events",
    ),
    path(
        "investigations/<uuid:investigation_id>/events/",
        investigation_public_views.events,
        name="resource-investigation-events-slash",
    ),
]
