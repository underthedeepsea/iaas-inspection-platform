from django.urls import include, path


urlpatterns = [
    path("api/v1/conversations/", include("apps.conversations.urls")),
    path("api/internal/v1/batch/", include("apps.inspections.internal_urls")),
]
