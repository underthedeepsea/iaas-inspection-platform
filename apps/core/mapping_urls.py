from django.urls import path
from . import mapping_api as api

urlpatterns = [
    path("context/", api.context),
    path("bundles/", api.bundles),
    path("bundles/<uuid:bundle_id>/", api.detail),
    path("bundles/<uuid:bundle_id>/revisions/", api.revisions),
    path("bundles/<uuid:bundle_id>/rollback/", api.rollback),
    path("bundles/<uuid:bundle_id>/activate/", api.activate),
    path("bundles/<uuid:bundle_id>/validate/", api.validate),
    path("bundles/<uuid:bundle_id>/collect/", api.collect),
    path("bundles/<uuid:bundle_id>/batches/<uuid:batch_id>/", api.batch),
    path("bundles/<uuid:bundle_id>/enabled/", api.enabled, name="mapping-enabled"),
]
