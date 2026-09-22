from django.urls import path

from . import api


urlpatterns = [
    path("inference-performance/snapshots", api.snapshots, name="inference-performance-snapshots"),
    path("inference-performance/snapshots/", api.snapshots, name="inference-performance-snapshots-slash"),
    path("inference-performance/snapshots/batch", api.snapshots_batch, name="inference-performance-snapshots-batch"),
    path("inference-performance/snapshots/batch/", api.snapshots_batch, name="inference-performance-snapshots-batch-slash"),
    path("inference-performance/engines/<path:engine_id>/profile", api.engine_profile, name="inference-performance-profile"),
    path("inference-performance/engines/<path:engine_id>/profile/", api.engine_profile, name="inference-performance-profile-slash"),
]
