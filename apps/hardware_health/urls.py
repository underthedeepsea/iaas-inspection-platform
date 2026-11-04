from django.urls import path
from . import api, profile_api
urlpatterns=[path('hardware-health/snapshots/batch',api.snapshots_batch),path('hardware-health/snapshots/batch/',api.snapshots_batch),path('hardware-health/snapshots',api.snapshots),path('hardware-health/snapshots/',api.snapshots),
             path('hardware-health/profiles',api.profiles),path('hardware-health/profiles/',api.profiles)]

urlpatterns += [path('hardware-health/performance-profiles', profile_api.profiles), path('hardware-health/performance-profiles/', profile_api.profiles), path('hardware-health/clusters/<uuid:cluster_id>/deployment', profile_api.cluster_deployment), path('hardware-health/clusters/<uuid:cluster_id>/deployment/', profile_api.cluster_deployment)]
