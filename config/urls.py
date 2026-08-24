from django.shortcuts import render
from django.urls import include, path


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


urlpatterns = [
    path("api/v1/", include("apps.api.urls")),
    path("api/internal/v1/mock/", include("apps.mockdata.internal_urls")),
    path("api/internal/v1/batch/", include("apps.inspections.internal_urls")),
    path("", app_page, {"page": "dashboard"}, name="web-dashboard"),
    path("risks", app_page, {"page": "risks"}, name="web-risks"),
    path("risks/", app_page, {"page": "risks"}),
    path("risks/<uuid:risk_id>", app_page, {"page": "risk-detail"}, name="web-risk-detail"),
    path("risks/<uuid:risk_id>/", app_page, {"page": "risk-detail"}),
    path("history", app_page, {"page": "history"}, name="web-history"),
    path("history/", app_page, {"page": "history"}),
    path("pending", app_page, {"page": "pending"}, name="web-pending"),
    path("pending/", app_page, {"page": "pending"}),
    path("capabilities", app_page, {"page": "capabilities"}, name="web-capabilities"),
    path("capabilities/", app_page, {"page": "capabilities"}),
    path("evolution", app_page, {"page": "evolution"}, name="web-evolution"),
    path("evolution/", app_page, {"page": "evolution"}),
    path("experiences", app_page, {"page": "experiences"}, name="web-experiences"),
    path("experiences/", app_page, {"page": "experiences"}),
    path("ai-runtime", app_page, {"page": "ai-runtime"}, name="web-ai-runtime"),
    path("ai-runtime/", app_page, {"page": "ai-runtime"}),
    path("settings", app_page, {"page": "settings"}, name="web-settings"),
    path("settings/", app_page, {"page": "settings"}),
    path("about", product_about, name="web-about"),
    path("about/", product_about),
    path("product-about", product_about),
    path("product-about/", product_about),
]
