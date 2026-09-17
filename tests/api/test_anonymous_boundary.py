import pytest
from django.apps import apps
from django.test import Client


@pytest.mark.parametrize("path", ["auth/login", "auth/me", "auth/logout", "missing-resource"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_removed_auth_and_unknown_api_paths_return_ordinary_not_found(path, method):
    response = getattr(Client(), method)(f"/api/v1/{path}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_no_account_or_session_apps_are_installed():
    assert not any(apps.is_installed(name) for name in (
        "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions"
    ))
