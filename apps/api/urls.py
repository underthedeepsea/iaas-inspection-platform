from django.urls import path

from . import views


urlpatterns = [
    path("", views.authenticated_not_found, name="api-root"),
    path("health", views.health, name="api-health"),
    path("health/", views.health, name="api-health-slash"),
    path("product-info", views.product_info, name="api-product-info"),
    path("product-info/", views.product_info, name="api-product-info-slash"),
    path("<path:resource>", views.authenticated_not_found, name="api-not-found"),
]
