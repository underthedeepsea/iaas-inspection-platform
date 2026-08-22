import uuid

from django.db import connection


def test_database_health_and_environment_creation(django_db_blocker):
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)

        from apps.core.models import Environment

        environment = Environment.objects.create(
            name="Development",
            slug=f"development-{uuid.uuid4().hex}",
        )
        try:
            assert environment.pk is not None
        finally:
            environment.delete()
