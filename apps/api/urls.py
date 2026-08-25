from django.urls import include, path, re_path

from . import views


urlpatterns = [
    path("", views.authenticated_not_found, name="api-root"),
    path("health", views.health, name="api-health"),
    path("health/", views.health, name="api-health-slash"),
    path("product-info", views.product_info, name="api-product-info"),
    path("product-info/", views.product_info, name="api-product-info-slash"),
    path("", include("apps.operations_api.urls")),
    path("", include("apps.inspections.urls")),
    re_path(r"^capabilities(?:/|$)", include("apps.capability_api.urls")),
    re_path(r"^conversations(?:/|$)", include("apps.conversations.urls")),
    re_path(r"^investigations(?:/|$)", include("apps.investigations.public_urls")),
    re_path(r"^feedback(?:/|$)", include("apps.feedback.urls")),
    path("", include("apps.experiences.urls")),
    re_path(r"^mock-datasets(?:/|$)", include("apps.mockdata.public_urls")),
    path("<path:resource>", views.authenticated_not_found, name="api-not-found"),
]
