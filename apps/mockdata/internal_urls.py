from django.urls import path

from . import internal_views


urlpatterns = [
    path("metrics/query", internal_views.metrics, name="mock-metrics-query"),
    path("metrics/query/", internal_views.metrics, name="mock-metrics-query-slash"),
    path("logs/search", internal_views.logs, name="mock-logs-search"),
    path("logs/search/", internal_views.logs, name="mock-logs-search-slash"),
    path("events/query", internal_views.events, name="mock-events-query"),
    path("events/query/", internal_views.events, name="mock-events-query-slash"),
    path("topology/query", internal_views.topology, name="mock-topology-query"),
    path("topology/query/", internal_views.topology, name="mock-topology-query-slash"),
]
