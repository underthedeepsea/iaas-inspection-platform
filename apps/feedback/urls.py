from django.urls import path

from . import views


urlpatterns = [
    path("", views.collection, name="feedback-collection"),
    path(
        "<uuid:feedback_id>/create-experience",
        views.convert,
        name="feedback-create-experience-no-slash",
    ),
    path(
        "<uuid:feedback_id>/create-experience/",
        views.convert,
        name="feedback-create-experience",
    ),
]
