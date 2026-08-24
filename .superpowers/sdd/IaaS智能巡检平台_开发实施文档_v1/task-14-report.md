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
- `apps/api/urls.py` is intentionally limited to foundation routes and an
  authenticated unknown-path fallback. `config/urls.py` includes it without
  importing future domain slices.

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

Remaining Task 14 domain slice URLs and serializers are intentionally outside
this foundation commit.
