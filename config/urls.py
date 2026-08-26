from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import include, path, re_path
from django.views.static import serve


def app_page(request, page="dashboard", risk_id=None):
    return render(
        request,
        "app.html",
        {
            "page": page,
            "risk_id": str(risk_id or ""),
        },
    )


def product_about(request):
    return render(request, "product_about.html")


def react_app(request, **kwargs):
    """Serve one React entry point for every formal web route."""

    del kwargs
    entrypoint = Path(settings.BASE_DIR) / "frontend" / "dist" / "index.html"
    if entrypoint.is_file():
        return HttpResponse(entrypoint.read_text(encoding="utf-8"), content_type="text/html")
    return render(request, "react_app.html")


def react_asset(request, path):
    return serve(request, path, document_root=str(Path(settings.BASE_DIR) / "frontend" / "dist"))


urlpatterns = [
    path("api/v1/", include("apps.api.urls")),
    path("api/internal/v1/mock/", include("apps.mockdata.internal_urls")),
    path("api/internal/v1/batch/", include("apps.inspections.internal_urls")),
    re_path(r"^assets/(?P<path>.*)$", react_asset, name="react-asset"),
    path("", react_app, name="web-dashboard"),
    path("login", react_app, name="web-login"),
    path("login/", react_app),
    path("resources", react_app, name="web-resources"),
    path("resources/", react_app),
    path("resources/<path:resource_path>", react_app, name="web-resource-route"),
    path("risks", react_app, name="web-risks"),
    path("risks/", react_app),
    path("risks/<uuid:risk_id>", react_app, name="web-risk-detail"),
    path("risks/<uuid:risk_id>/", react_app),
    path("history", react_app, name="web-history"),
    path("history/", react_app),
    path("pending", react_app, name="web-pending"),
    path("pending/", react_app),
    path("capabilities", react_app, name="web-capabilities"),
    path("capabilities/", react_app),
    path("evolution", react_app, name="web-evolution"),
    path("evolution/", react_app),
    path("experiences", react_app, name="web-experiences"),
    path("experiences/", react_app),
    path("ai-runtime", react_app, name="web-ai-runtime"),
    path("ai-runtime/", react_app),
    path("settings", react_app, name="web-settings"),
    path("settings/", react_app),
    path("about", react_app, name="web-about"),
    path("about/", react_app),
    path("product-about", react_app),
    path("product-about/", react_app),
]
