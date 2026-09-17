from pathlib import Path
from uuid import uuid4

import pytest
from django.test import Client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROUTES = (
    "/",
    "/resources",
    "/resources/llm-runtime",
    "/resources/llm-runtime/runs/00000000-0000-0000-0000-000000000001",
    "/risks",
    "/ai-runtime",
    "/about",
)
REMOVED_ROUTES = (
    "/login",
    "/history",
    "/pending",
    "/capabilities",
    "/evolution",
    "/experiences",
    "/settings",
    "/product-about",
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


@pytest.mark.parametrize("route", REMOVED_ROUTES)
def test_removed_placeholder_and_login_routes_return_not_found(route):
    assert Client().get(route).status_code == 404


def test_legacy_page_shell_files_are_removed():
    removed = (
        "templates/app.html",
        "templates/product_about.html",
        "static/js/app.js",
        "static/js/conversation.js",
        "static/css/app.css",
    )
    for relative_path in removed:
        assert not (PROJECT_ROOT / relative_path).exists(), relative_path


def test_built_frontend_assets_are_served_from_the_assets_directory(tmp_path, settings):
    settings.BASE_DIR = str(tmp_path)
    assets = tmp_path / 'frontend' / 'dist' / 'assets'
    assets.mkdir(parents=True)
    (assets / 'app.js').write_text('window.mvpReady = true;')
    response = Client().get('/assets/app.js')
    assert response.status_code == 200
    assert b''.join(response.streaming_content) == b'window.mvpReady = true;'
    assert Client().get('/assets/../index.html').status_code == 400
