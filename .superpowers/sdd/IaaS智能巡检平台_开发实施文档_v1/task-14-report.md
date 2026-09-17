# Task 14 report

## 14.1 Shared HTTP foundation

### RED / GREEN

- Added `tests/api/test_public_api_foundation.py` before the shared API package.
- RED: `pytest -q tests/api/test_public_api_foundation.py` failed during
  collection with `ModuleNotFoundError: No module named 'apps.api'`.
- GREEN: the focused foundation suite passes with `31 passed`.

### Implementation

- `apps/api/http.py` provides the stable
  `error.code/message/details/trace_id` envelope, strict JSON-object,
  boolean, and bounded integer parsing.
- `apps/api/auth.py` enforces Django Session Authentication, the
  `viewer < operator < platform_admin` group hierarchy, superuser elevation,
  and ownership-scoped lookup.
- `apps/api/pagination.py` returns bounded `items/page/page_size/total`
  responses with default `page=1,page_size=50` and a configurable maximum.
- `apps/api/views.py` provides anonymous GET health/product-info endpoints;
  database health is checked with `SELECT 1`, while Ollama/Airflow checks are
  callback-injectable through `API_HEALTH_CHECKS` and never contact external
  services by default. Product/vendor versions are fixed to the documented
  numeric values and the project `VERSION` is read and validated as `x.x.x`.
- `apps/api/urls.py` keeps foundation endpoints first, then mounts each domain
  slice once and ends with an authenticated unknown-path fallback. The
  internal mock query slice is mounted separately by `config/urls.py`.

### Foundation verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q \
  tests/api/test_public_api_foundation.py
31 passed in 2.15s

DJANGO_SETTINGS_MODULE=config.settings.dev \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q \
  tests/api/test_conversation_api.py tests/api/test_internal_batch_api.py
14 passed in 6.47s
```

## 14.2–14.4 Parallel slice integration evidence

The three authorized slices remained in the worktree and were integrated as
one surface. Their focused tests were run serially during integration.

| RED boundary found during integration | GREEN result |
| --- | --- |
| Operations detail serializers referenced the opposite slice variable and returned 500 | Item/risk detail projections pass, including bounded codeization fields |
| Patched Airflow transport was treated as a mock `.trigger` object, so a failing callable incorrectly returned 202 | Callable transport is invoked directly; failure maps to `AIRFLOW_TRIGGER_FAILED`/502 |
| Conversation bodies accepted JSON `NaN` and returned a pre-foundation error shape | Shared strict JSON-object parser and stable `VALIDATION_ERROR` envelope |
| Conversation create/turn writes had no integrated same-transaction audit; audit failure could render HTML | `conversation.created` and `conversation.turn.created` are single semantic events and rollback to stable 500 |
| Public conversation messages exposed provider/model fields and had no public row cap | Provider/model fields are omitted and messages are capped at 100 |
| Internal mock rows returned secret-like log/event text and unrestricted labels/topology | Text is bounded/redacted; nested mappings are bounded and sensitive keys are removed |
| Inspection-run detail fetched every nested item-run before slicing the response | Database query is capped at 128 rows; observation lookup is single-row |
| Close audit failure escaped as HTML 500 | Outer transaction rolls back the status change and returns stable `INTERNAL_ERROR` |

The focused API run after these fixes is `120 passed` (`tests/api`). The
contract matrix itself is `31 passed`; its initial URL RED run had 29 route
failures because the domain modules were not mounted. The matrix now also
proves no-slash mounted prefixes and the section-37 `METHOD_NOT_ALLOWED`
code for unsupported methods.

## 14.5 Route matrix

All routes below are mounted below `/api/v1/`; `viewer` is the minimum session
role unless noted. Both slash forms are accepted by the mounted public slices.
The executable matrix is
`tests/api/test_public_api_contract_matrix.py`.

| Surface | Routes and methods |
| --- | --- |
| Health/product | `GET /health`, `GET /product-info` (anonymous) |
| Operations | `GET /dashboard/today`; `GET /daily-snapshots`, `/daily-snapshots/{id}`; `GET /inspection-items`, `/inspection-items/{id}`; `POST /inspection-items/{id}/ask`; `GET /inspection-runs`, `/inspection-runs/{id}`, `/inspection-item-runs/{id}`; `POST /inspection-runs/trigger`; `GET /findings`; `GET /risks`, `/risks/{id}`, `/risks/{id}/timeline`, `/risks/{id}/evidence`; `POST /risks/{id}/mark-handled`, `/ignore`, `/reverify`; `POST /risks/{id}/investigations` |
| Capabilities | `GET /capabilities`, `/capabilities/{id}`; `POST /capabilities`, `/capabilities/{id}/versions`, `/capabilities/{id}/versions/{version}/test|shadow|activate`; `POST /capabilities/resolve`. Capability writes/transitions require `platform_admin`. |
| Conversations | `POST /conversations`; `GET /conversations/{id}`, `/messages`, `/turns/{turn_id}/events`; `POST /conversations/{id}/turns`, `/close` |
| Investigations | `GET /investigations/{id}`, `/events`, `/tool-calls`; `POST /investigations/{id}/cancel` (`operator`) |
| Feedback | `GET|POST /feedback`; `POST /feedback/{id}/create-experience` (`operator`) |
| Experiences/codeization | `GET /experiences`, `/experiences/{id}`, `/codeization-tasks`; `POST /experiences/{id}/confirm`, `/codeization-tasks`; `PATCH /codeization-tasks/{id}` (`operator`, status progression additionally `platform_admin`) |
| Mock datasets | `GET /mock-datasets`, `/mock-datasets/{id}`; `POST /mock-datasets/generate` (`operator`) |

Internal mock query routes are deliberately outside session auth and are
mounted only at `/api/internal/v1/mock/`: token-protected `POST
metrics/query`, `logs/search`, `events/query`, and `topology/query`.

## Verification

Final integration verification:

- all API/Task 14 tests: `120 passed in 23.64s`
- full Web suite: `329 passed in 28.05s`
- `manage.py check`: `System check identified no issues (0 silenced)`
- `manage.py makemigrations --check --dry-run`: `No changes detected`
- `python -m compileall -q apps config tests`: passed
- `git diff --check`: passed

Known coverage gap: the matrix validates route reachability, method, session,
and role contracts using missing-resource fixtures; it does not replace the
domain mutation suites or an external Airflow/Ollama deployment.
