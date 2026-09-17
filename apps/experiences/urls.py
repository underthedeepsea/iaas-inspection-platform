from django.urls import path

from . import views


urlpatterns = [
    path("experiences", views.collection, name="experience-collection-no-slash"),
    path("experiences/", views.collection, name="experience-collection"),
    path("experiences/<uuid:experience_id>", views.detail, name="experience-detail-no-slash"),
    path("experiences/<uuid:experience_id>/", views.detail, name="experience-detail"),
    path(
        "experiences/<uuid:experience_id>/confirm",
        views.confirm,
        name="experience-confirm-no-slash",
    ),
    path(
        "experiences/<uuid:experience_id>/confirm/",
        views.confirm,
        name="experience-confirm",
    ),
    path(
        "experiences/<uuid:experience_id>/codeization-tasks",
        views.create_task,
        name="experience-codeization-task-create-no-slash",
    ),
    path(
        "experiences/<uuid:experience_id>/codeization-tasks/",
        views.create_task,
        name="experience-codeization-task-create",
    ),
    path("codeization-tasks", views.task_collection, name="codeization-task-collection-no-slash"),
    path("codeization-tasks/", views.task_collection, name="codeization-task-collection"),
    path(
        "codeization-tasks/<uuid:task_id>",
        views.task_detail,
        name="codeization-task-detail-no-slash",
    ),
    path(
        "codeization-tasks/<uuid:task_id>/",
        views.task_detail,
        name="codeization-task-detail",
    ),
]
