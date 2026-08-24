"""Slice-local URL patterns for operations and risk resources."""

from django.urls import path

from . import views


urlpatterns = [
    path("dashboard/today", views.dashboard_today, name="dashboard-today"),
    path("dashboard/today/", views.dashboard_today, name="dashboard-today-slash"),
    path("daily-snapshots", views.daily_snapshots, name="daily-snapshots"),
    path("daily-snapshots/", views.daily_snapshots, name="daily-snapshots-slash"),
    path("daily-snapshots/<uuid:snapshot_id>", views.daily_snapshot_detail, name="daily-snapshot-detail"),
    path("daily-snapshots/<uuid:snapshot_id>/", views.daily_snapshot_detail, name="daily-snapshot-detail-slash"),
    path("inspection-items", views.inspection_items, name="inspection-items"),
    path("inspection-items/", views.inspection_items, name="inspection-items-slash"),
    path("inspection-items/<uuid:item_id>", views.inspection_item_detail, name="inspection-item-detail"),
    path("inspection-items/<uuid:item_id>/", views.inspection_item_detail, name="inspection-item-detail-slash"),
    path("inspection-items/<uuid:item_id>/ask", views.inspection_item_ask, name="inspection-item-ask"),
    path("inspection-items/<uuid:item_id>/ask/", views.inspection_item_ask, name="inspection-item-ask-slash"),
    path("inspection-runs/trigger", views.trigger_inspection_run, name="inspection-runs-trigger"),
    path("inspection-runs/trigger/", views.trigger_inspection_run, name="inspection-runs-trigger-slash"),
    path("inspection-runs", views.inspection_runs, name="inspection-runs"),
    path("inspection-runs/", views.inspection_runs, name="inspection-runs-slash"),
    path("inspection-runs/<uuid:run_id>", views.inspection_run_detail, name="inspection-run-detail"),
    path("inspection-runs/<uuid:run_id>/", views.inspection_run_detail, name="inspection-run-detail-slash"),
    path("inspection-item-runs/<uuid:item_run_id>", views.inspection_item_run_detail, name="inspection-item-run-detail"),
    path("inspection-item-runs/<uuid:item_run_id>/", views.inspection_item_run_detail, name="inspection-item-run-detail-slash"),
    path("findings", views.findings, name="findings"),
    path("findings/", views.findings, name="findings-slash"),
    path("risks", views.risks, name="risks"),
    path("risks/", views.risks, name="risks-slash"),
    path("risks/<uuid:risk_id>", views.risk_detail, name="risk-detail"),
    path("risks/<uuid:risk_id>/", views.risk_detail, name="risk-detail-slash"),
    path("risks/<uuid:risk_id>/timeline", views.risk_timeline, name="risk-timeline"),
    path("risks/<uuid:risk_id>/timeline/", views.risk_timeline, name="risk-timeline-slash"),
    path("risks/<uuid:risk_id>/evidence", views.risk_evidence, name="risk-evidence"),
    path("risks/<uuid:risk_id>/evidence/", views.risk_evidence, name="risk-evidence-slash"),
    path("risks/<uuid:risk_id>/mark-handled", views.mark_handled, name="risk-mark-handled"),
    path("risks/<uuid:risk_id>/mark-handled/", views.mark_handled, name="risk-mark-handled-slash"),
    path("risks/<uuid:risk_id>/ignore", views.ignore, name="risk-ignore"),
    path("risks/<uuid:risk_id>/ignore/", views.ignore, name="risk-ignore-slash"),
    path("risks/<uuid:risk_id>/reverify", views.reverify, name="risk-reverify"),
    path("risks/<uuid:risk_id>/reverify/", views.reverify, name="risk-reverify-slash"),
    path("risks/<uuid:risk_id>/investigations", views.risk_investigations, name="risk-investigations"),
    path("risks/<uuid:risk_id>/investigations/", views.risk_investigations, name="risk-investigations-slash"),
]
