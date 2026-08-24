from pathlib import Path
from uuid import uuid4

import pytest
from django.test import Client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROUTES = (
    "/",
    "/risks",
    "/capabilities",
    "/evolution",
    "/experiences",
    "/ai-runtime",
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
def test_app_routes_render_a_safe_shell(route):
    response = Client().get(route)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert "每日巡检" in response.content.decode()
    assert "风险中心" in response.content.decode()
    assert b"<details" in response.content
    assert b" open" not in response.content
    assert b"Raw JSON" not in response.content
    assert b"Prompt" not in response.content
    assert "Tool 参数" not in response.content.decode()


def test_risk_detail_route_keeps_risk_id_for_the_ai_drawer():
    risk_id = uuid4()

    response = Client().get(f"/risks/{risk_id}")

    assert response.status_code == 200
    body = response.content.decode()
    assert 'data-page="risk-detail"' in body
    assert f'data-risk-id="{risk_id}"' in body
    assert "询问 AI" in body


def test_product_about_covers_the_product_contract():
    response = Client().get("/about")
    body = response.content.decode()

    assert response.status_code == 200
    for topic in (
        "这个系统解决什么问题",
        "每日巡检如何工作",
        "为什么不是所有问题都交给 LLM",
        "Code / AI 如何分工",
        "插件化是什么",
        "什么叫代码化程度",
        "人工反馈如何帮助系统进化",
        "为什么“已处理”后还要自动复验",
        "当前 Demo 使用模拟数据",
        "LLM 本地开发使用 Ollama",
        "安全边界：只读 Tool Calling",
        "术语解释",
    ):
        assert topic in body


def test_task_15_static_modules_are_present():
    for relative_path in STATIC_MODULES:
        assert (PROJECT_ROOT / relative_path).is_file(), relative_path
