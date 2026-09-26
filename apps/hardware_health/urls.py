from django.urls import path
from . import api
urlpatterns=[path('hardware-health/snapshots/batch',api.snapshots_batch),path('hardware-health/snapshots/batch/',api.snapshots_batch),path('hardware-health/snapshots',api.snapshots),path('hardware-health/snapshots/',api.snapshots),
             path('hardware-health/profiles',api.profiles),path('hardware-health/profiles/',api.profiles)]
