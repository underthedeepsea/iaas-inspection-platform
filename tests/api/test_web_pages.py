from pathlib import Path
from uuid import uuid4

import pytest
from django.test import Client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROUTES = (
    "/",
    "/login",
    "/resources",
    "/resources/llm-runtime",
    "/resources/llm-runtime/runs/00000000-0000-0000-0000-000000000001",
    "/risks",
    "/history",
    "/pending",
    "/capabilities",
    "/evolution",
    "/experiences",
    "/ai-runtime",
    "/settings",
    "/about",
)
STATIC_MODULES = (
    "static/js/api.js",
    "static/js/app.js",
    "static/js/dashboard.js",
    "static/js/risks.js",
    "static/js/capabilities.js",
    "static/js/conversation.js",
    "static/js/about.js",
    "static/css/app.css",
)


@pytest.mark.parametrize("route", APP_ROUTES)
def test_formal_app_routes_render_one_react_shell(route):
    response = Client().get(route)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    body = response.content.decode()
    assert '<div id="root"></div>' in body
    assert "Demo v4.1" not in body
    assert "本地演示环境" not in body
    assert 'data-page="' not in body


def test_risk_detail_route_uses_the_react_shell():
    risk_id = uuid4()

    response = Client().get(f"/risks/{risk_id}")

    assert response.status_code == 200
    body = response.content.decode()
    assert '<div id="root"></div>' in body
    assert "Demo v4.1" not in body


def test_formal_resource_routes_serve_the_react_application_shell():
    response = Client().get("/resources/llm-runtime/runs/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 200
    body = response.content.decode()
    assert '<div id="root"></div>' in body
    assert "Demo v4.1" not in body
    assert "本地演示环境" not in body


def test_product_about_uses_the_react_shell():
    response = Client().get("/about")
    body = response.content.decode()

    assert response.status_code == 200
    assert '<div id="root"></div>' in body
    assert "当前 Demo 使用模拟数据" not in body
    assert "LLM 本地开发使用 Ollama" not in body


def test_task_15_static_modules_are_present():
    for relative_path in STATIC_MODULES:
        assert (PROJECT_ROOT / relative_path).is_file(), relative_path
