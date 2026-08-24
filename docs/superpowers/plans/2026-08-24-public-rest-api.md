# Public REST API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the documented `/api/v1` contracts in sections 38–49 with session authentication, role checks, stable errors, audit events, and bounded serializers.

**Architecture:** A small shared `apps.api` package owns authentication, role hierarchy, error envelopes, request parsing, pagination, and root URL composition. Three independent domain slices own operations/risk APIs, capability/mock APIs, and investigation/learning APIs. Domain services remain authoritative for mutations; views validate HTTP input and serialize bounded persisted results.

**Tech Stack:** Python 3.10.x, Django 4.2.16, Django REST Framework 3.15.x, PostgreSQL 14.x, pytest/pytest-django.

**Spec:** `设计文档/IaaS智能巡检平台_开发实施文档_v1.md` sections 36–49 and Task 14.

## Global Constraints

- Project-owned versions use numeric `x.x.x`.
- `/api/v1/health` and `/api/v1/product-info` allow anonymous GET; every other `/api/v1/*` requires Django Session Authentication.
- Role order is `viewer < operator < platform_admin`; superusers satisfy all roles.
- Every write API emits a non-sensitive `AuditEvent` in the same successful transaction as its mutation.
- Reuse existing Task 7–13 services; views must not duplicate lifecycle, registry, graph, feedback, or codeization state machines.
- Error responses use `{"error":{"code","message","details","trace_id"}}` with the section 37 status mapping.
- List endpoints use bounded pagination, default `page=1,page_size=50`, and never serialize unrestricted raw Evidence/tool/provider payloads.
- Apply Ponytail full: no new dependency, router framework, generic repository, speculative async worker, or duplicate model layer.

---

### Task 14.1: Shared HTTP foundation

**Files:**
- Create: `apps/api/auth.py`
- Create: `apps/api/http.py`
- Create: `apps/api/pagination.py`
- Create: `apps/api/views.py`
- Create: `apps/api/urls.py`
- Modify: `config/urls.py`
- Test: `tests/api/test_public_api_foundation.py`

**Interfaces:**
- Produces: `api_error(code, message, *, status, details=None) -> JsonResponse`
- Produces: `parse_json_object(request) -> dict`, `parse_bool(value) -> bool`, `parse_positive_int(value, ...) -> int`
- Produces: `require_session(request)`, `require_role(request, minimum)` and `owned_or_404(queryset, user, **lookup)`
- Produces: `paginate(queryset, request, serializer) -> JsonResponse`

- [ ] Write failing tests for anonymous/public endpoints, `AUTH_REQUIRED`, viewer/operator/admin hierarchy, stable error shape, strict JSON/boolean parsing, bounded pagination, health DB state, and exact numeric product versions.
- [ ] Run `pytest -q tests/api/test_public_api_foundation.py` and confirm feature failures.
- [ ] Implement the minimal shared helpers and anonymous health/product views; do not import optional domain URL modules yet.
- [ ] Run the focused tests and the existing conversation/internal API suites.
- [ ] Commit only the shared foundation.

### Task 14.2: Dashboard, inspection, run, finding, and risk APIs

**Files:**
- Create: `apps/operations_api/views.py`
- Create: `apps/operations_api/serializers.py`
- Create: `apps/operations_api/urls.py`
- Test: `tests/api/test_operations_public_api.py`
- Test: `tests/api/test_risk_public_api.py`

**Interfaces:**
- Consumes: Task 14.1 auth/error/pagination helpers and Task 6–8 lifecycle/snapshot services.
- Produces: sections 39–42 endpoints under a slice-local `urlpatterns`.

- [ ] Write failing contract tests for snapshot/dashboard filters and 7-day/yesterday calculations; inspection item list/detail; run/item-run/finding filters; risk list/detail/timeline/evidence.
- [ ] Write failing mutation tests proving `mark-handled`, `ignore`, `reverify`, and `investigations` use existing domain services, reject illegal transitions, never set `RECOVERED` directly, require operator, and emit AuditEvent atomically.
- [ ] Implement bounded serializers and views without changing `apps/api/urls.py` or `config/urls.py`.
- [ ] Run both focused files plus Task 7–8 domain regressions.
- [ ] Leave changes uncommitted for the integration task; report exact files and tests.

### Task 14.3: Capability and mock-data APIs

**Files:**
- Create: `apps/capability_api/views.py`
- Create: `apps/capability_api/serializers.py`
- Create: `apps/capability_api/urls.py`
- Create: `apps/mockdata/public_views.py`
- Create: `apps/mockdata/public_urls.py`
- Create: `apps/mockdata/internal_views.py`
- Create: `apps/mockdata/internal_urls.py`
- Test: `tests/api/test_capability_public_api.py`
- Test: `tests/api/test_mockdata_api.py`

**Interfaces:**
- Consumes: Task 14.1 helpers, `CapabilityRegistry`, plugin schemas/executors, and `apps.mockdata.services`.
- Produces: sections 43 and 49 plus section 50 bounded internal mock query endpoints.

- [ ] Write failing tests for capability filters/detail, admin-only create/version/shadow/activate, semantic `x.x.x`, schema/read-only gates, resolver output, and AuditEvent rollback.
- [ ] Write failing tests for authenticated dataset generation/list/detail and token-protected bounded metric/log/event/topology queries.
- [ ] Implement views and bounded serializers; call existing registry/codeization logic where applicable and never execute arbitrary scripts from HTTP input.
- [ ] Run focused files plus registry/plugin-security/mock-generator regressions.
- [ ] Leave changes uncommitted for integration; report exact files and tests.

### Task 14.4: Conversation, investigation, feedback, experience, and codeization APIs

**Files:**
- Modify: `apps/conversations/views.py`
- Modify: `apps/conversations/urls.py`
- Create: `apps/investigations/public_views.py`
- Create: `apps/investigations/public_urls.py`
- Create: `apps/feedback/views.py`
- Create: `apps/feedback/urls.py`
- Create: `apps/experiences/views.py`
- Create: `apps/experiences/urls.py`
- Test: `tests/api/test_learning_public_api.py`
- Test: `tests/api/test_investigation_public_api.py`

**Interfaces:**
- Consumes: Task 12 ownership/SSE services and Task 13 feedback/experience/codeization services.
- Produces: conversation close plus sections 45, 46, and 48 endpoints with slice-local URL patterns.

- [ ] Write failing tests for owner-scoped investigation/events/tool calls/cancel; conversation close; feedback create/list/convert; experience list/detail/confirm/task creation; codeization list/update.
- [ ] Prove operator/admin permissions and AuditEvent creation; platform-admin is required for codeization state progression.
- [ ] Implement views as thin validation/serialization layers over Task 12–13 services; do not expose raw ToolCall/Evidence/provider fields.
- [ ] Run focused files plus Task 12–13 regressions.
- [ ] Leave changes uncommitted for integration; report exact files and tests.

### Task 14.5: URL integration, contract matrix, and verification

**Files:**
- Modify: `apps/api/urls.py`
- Modify: `config/urls.py` only if required by the foundation contract
- Test: `tests/api/test_public_api_contract_matrix.py`
- Create: `.superpowers/sdd/IaaS智能巡检平台_开发实施文档_v1/task-14-report.md`

**Interfaces:**
- Consumes: the three slice-local `urlpatterns` and all shared helpers.
- Produces: one reachable `/api/v1` surface matching sections 38–49.

- [ ] Add a failing route/method/auth contract matrix covering every section 38–49 path and expected anonymous/authenticated/role behavior.
- [ ] Include each slice URL module exactly once and resolve route/name collisions.
- [ ] Review every mutation for same-transaction non-sensitive AuditEvent and every list for pagination/filter bounds.
- [ ] Run all Task 14 tests, then the full Web suite, Django check, migration drift check, compileall, and `git diff --check`.
- [ ] Write RED/GREEN evidence and exact coverage gaps in the report, then commit the integrated Task 14 change.
