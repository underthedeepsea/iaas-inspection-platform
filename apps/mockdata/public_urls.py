from django.urls import path

from . import public_views


urlpatterns = [
    path("generate", public_views.generate, name="mock-dataset-generate"),
    path("generate/", public_views.generate, name="mock-dataset-generate-slash"),
    path("", public_views.collection, name="mock-dataset-collection"),
    path("<uuid:dataset_id>", public_views.detail, name="mock-dataset-detail"),
    path("<uuid:dataset_id>/", public_views.detail, name="mock-dataset-detail-slash"),
]
