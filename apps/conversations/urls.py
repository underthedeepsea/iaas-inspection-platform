from django.urls import path

from . import views


urlpatterns = [
    path("", views.collection, name="conversation-collection"),
    path("<uuid:conversation_id>/", views.detail, name="conversation-detail"),
    path("<uuid:conversation_id>/messages/", views.messages, name="conversation-messages"),
    path("<uuid:conversation_id>/turns/", views.turns, name="conversation-turns"),
    path(
        "<uuid:conversation_id>/turns/<str:turn_id>/events/",
        views.events,
        name="conversation-events",
    ),
    path("<uuid:conversation_id>/close/", views.close, name="conversation-close"),
]
