from django.urls import include, path


urlpatterns = [
    path("api/internal/v1/batch/", include("apps.inspections.internal_urls")),
]
