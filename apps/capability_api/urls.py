from django.urls import path

from . import views


urlpatterns = [
    path("", views.collection, name="capability-collection"),
    path("resolve", views.resolve, name="capability-resolve"),
    path("resolve/", views.resolve, name="capability-resolve-slash"),
    path("<str:capability_id>", views.detail, name="capability-detail"),
    path("<str:capability_id>/", views.detail, name="capability-detail-slash"),
    path("<str:capability_id>/versions", views.versions, name="capability-versions"),
    path("<str:capability_id>/versions/", views.versions, name="capability-versions-slash"),
    path(
        "<str:capability_id>/versions/<str:version>/test",
        views.test_version,
        name="capability-version-test",
    ),
    path(
        "<str:capability_id>/versions/<str:version>/test/",
        views.test_version,
        name="capability-version-test-slash",
    ),
    path(
        "<str:capability_id>/versions/<str:version>/shadow",
        views.shadow,
        name="capability-version-shadow",
    ),
    path(
        "<str:capability_id>/versions/<str:version>/shadow/",
        views.shadow,
        name="capability-version-shadow-slash",
    ),
    path(
        "<str:capability_id>/versions/<str:version>/activate",
        views.activate,
        name="capability-version-activate",
    ),
    path(
        "<str:capability_id>/versions/<str:version>/activate/",
        views.activate,
        name="capability-version-activate-slash",
    ),
]
