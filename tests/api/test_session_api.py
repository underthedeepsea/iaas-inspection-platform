import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client


@pytest.mark.django_db
def test_session_login_me_and_logout_round_trip():
    user = get_user_model().objects.create_user(
        username=f"session-{uuid.uuid4().hex}",
        password="correct-password",
    )
    group, _ = Group.objects.get_or_create(name="viewer")
    user.groups.add(group)
    client = Client()

    login = client.post(
        "/api/v1/auth/login",
        data=json.dumps({"username": user.username, "password": "correct-password"}),
        content_type="application/json",
    )

    assert login.status_code == 200
    assert login.json()["username"] == user.username
    assert "viewer" in login.json()["roles"]

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user_id"] == str(user.pk)

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.django_db
def test_session_login_rejects_bad_credentials_without_leaking_auth_state():
    user = get_user_model().objects.create_user(
        username=f"session-invalid-{uuid.uuid4().hex}",
        password="correct-password",
    )

    response = Client().post(
        "/api/v1/auth/login",
        data=json.dumps({"username": user.username, "password": "wrong-password"}),
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"
