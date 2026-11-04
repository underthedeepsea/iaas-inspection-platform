from django.urls import path
from . import local_monitor_api as views

urlpatterns = [
    path("endpoint-metric", views.endpoint_metric, name="local-monitor-endpoint-metric"),
    path("batch-endpoint-counter", views.batch_endpoint_counter, name="local-monitor-batch-endpoint-counter"),
    path("data", views.data, name="local-monitor-data"),
    path("batch-data", views.batch_data, name="local-monitor-batch-data"),
]
