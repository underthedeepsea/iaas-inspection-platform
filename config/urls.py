from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import include, path, re_path
from django.views.static import serve


def react_app(request, **kwargs):
    """Serve one React entry point for every formal web route."""

    del kwargs
    entrypoint = Path(settings.BASE_DIR) / "frontend" / "dist" / "index.html"
    if entrypoint.is_file():
        return HttpResponse(entrypoint.read_text(encoding="utf-8"), content_type="text/html")
    return render(request, "react_app.html")


def react_asset(request, path):
    return serve(request, path, document_root=str(Path(settings.BASE_DIR) / "frontend" / "dist" / "assets"))


urlpatterns = [
    path("api/v1/", include("apps.api.urls")),
    path("api/internal/v1/mock/", include("apps.mockdata.internal_urls")),
    path("api/internal/v1/batch/", include("apps.inspections.internal_urls")),
    re_path(r"^assets/(?P<path>.*)$", react_asset, name="react-asset"),
    path("", react_app, name="web-dashboard"),
    path("code-plugins", react_app, name="web-code-plugins"),
    path("rules", react_app, name="web-rules"),
    path("inspection-runs/<uuid:run_id>", react_app, name="web-inspection-run-result"),
    path("resources", react_app, name="web-resources"),
    path("resources/", react_app),
    path("resources/<path:resource_path>", react_app, name="web-resource-route"),
    path("risks", react_app, name="web-risks"),
    path("risks/", react_app),
    path("risks/<uuid:risk_id>", react_app, name="web-risk-detail"),
    path("risks/<uuid:risk_id>/", react_app),
    path("ai-runtime", react_app, name="web-ai-runtime"),
    path("ai-runtime/", react_app),
    path("about", react_app, name="web-about"),
    path("about/", react_app),
]
