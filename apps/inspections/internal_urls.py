from django.urls import path

from . import api_internal


urlpatterns = [
    path("datasets/", api_internal.datasets, name="internal-batch-datasets"),
    path("inspection-runs/", api_internal.inspection_runs, name="internal-batch-inspection-runs"),
    path("inspection-runs/<str:run_id>/execute/", api_internal.execute, name="internal-batch-execute"),
    path(
        "inspection-runs/<str:run_id>/correlate-risks/",
        api_internal.correlate_risks,
        name="internal-batch-correlate-risks",
    ),
    path("inspection-runs/<str:run_id>/reverify/", api_internal.reverify, name="internal-batch-reverify"),
    path(
        "inspection-runs/<str:run_id>/resource-summaries/",
        api_internal.resource_summaries,
        name="internal-batch-resource-summaries",
    ),
    path("inspection-runs/<str:run_id>/snapshot/", api_internal.snapshot, name="internal-batch-snapshot"),
    path("inspection-runs/<str:run_id>/complete/", api_internal.complete, name="internal-batch-complete"),
]
