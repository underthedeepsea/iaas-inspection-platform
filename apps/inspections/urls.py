from django.urls import path

from . import api


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
        "resource-types/<str:resource_type_code>/inspection-history/<uuid:run_id>",
        api.resource_run_detail,
        name="resource-type-run-detail",
    ),
    path(
        "resource-types/<str:resource_type_code>/inspection-history/<uuid:run_id>/",
        api.resource_run_detail,
        name="resource-type-run-detail-slash",
    ),
]
