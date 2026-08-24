from django.urls import include, path


urlpatterns = [
    path("api/v1/", include("apps.api.urls")),
    path("api/internal/v1/mock/", include("apps.mockdata.internal_urls")),
    path("api/internal/v1/batch/", include("apps.inspections.internal_urls")),
]
