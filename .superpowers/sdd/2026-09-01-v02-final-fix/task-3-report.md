# Task 3 Report: Precise ResourceType Selectors

## Status

Implemented the bounded OR-term selector contract, data migration, fixture labels/assets, scope regressions, and frozen-scope coverage. The implementation changes only ResourceType scope handling, the mock fixture, the new selector data migration, and related scope tests. `homepage-16-9.png` was left unmodified and will be excluded from the commit.

## RED evidence

1. Added the two required scope tests before production changes:
   - `test_control_plane_scope_excludes_worker_host`
   - `test_llm_runtime_scope_excludes_control_plane_pods`
2. Initial sandbox test attempt could not connect to local PostgreSQL (`127.0.0.1:5432`, `Operation not permitted`), so no assertions could run there.
3. Retried the focused tests with controlled local PostgreSQL access:

   ```text
   DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/domain/test_inspection_scope.py tests/domain/test_frozen_scope_execution.py -q
   ....FF..
   FAILED test_control_plane_scope_excludes_worker_host
     'host-worker-0' was included in CONTROL_PLANE scope
   FAILED test_llm_runtime_scope_excludes_control_plane_pods
     'llm-runtime-0' was absent; control-plane pods were included
   2 failed, 6 passed
   ```

4. Added `test_mixed_fixture_has_resource_selector_labels` before changing the fixture:

   ```text
   DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/services/test_mock_generator.py -q -k resource_selector_labels
   FAILED ... KeyError: 'gpu_host'
   1 failed, 8 deselected
   ```

## Implementation

- Added frozen `SelectorTerm(asset_types, labels)` and changed `_validated_selector()` to return tuples of validated terms.
- The selector accepts only `selectors`, `asset_types`, and `labels`; the legacy single-selector mapping remains valid.
- Matching now evaluates each validated term independently and unions the matching active asset IDs.
- Added `0009_v02_precise_resource_selectors`, dependent on inspected predecessor `0008_v02_scope_and_no_data`, with exact forward selector data and a reverse to the `0008` selector values.
- Added the required fixture labels and the `llm-runtime-0` POD without changing the control-plane topology fixture.
- Updated legacy broad-scope expectations to assert strict non-overlapping CONTROL_PLANE and LLM_RUNTIME scopes.

## GREEN and verification evidence

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/services/test_mock_generator.py -q -k resource_selector_labels
1 passed, 8 deselected

DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/domain/test_inspection_scope.py tests/domain/test_frozen_scope_execution.py -q
8 passed
```

The requested broader focused command was then run:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests -q -k "scope or resource_type or manual_inspection"
```

It first found two old composition assertions, which were updated to the Task 3 contract. The rerun then found one remaining stale API response count (`4`, corrected to `3`). Per the user checkpoint instruction, the database-backed command was not rerun after that final local expectation correction.

Additional non-network checks after the final correction:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m compileall -q [changed Python files]
git diff --check
```

Both passed. `manage.py makemigrations --check` reported `No changes detected`, but emitted the same sandbox PostgreSQL access warning before the controlled retry was declined by the checkpoint instruction.

## Files changed

- `apps/inspections/services/scope.py`
- `apps/inspections/migrations/0009_v02_precise_resource_selectors.py`
- `services/mock_generator/generator.py`
- `tests/domain/test_inspection_scope.py`
- `tests/domain/test_frozen_scope_execution.py`
- `tests/domain/test_item_asset_scope.py`
- `tests/services/test_mock_generator.py`
- `tests/api/test_inspection_trigger_api.py`

## Self-review

- Confirmed the migration dependency is exactly `0008_v02_scope_and_no_data`.
- Confirmed no investigation or UI files changed.
- Confirmed the generator preserves `control-plane-0` and `control-plane-1` topology on `host-control-0` for Task 2 evidence consistency.
- Confirmed no diff whitespace errors and that the user-owned `homepage-16-9.png` remains untracked and excluded.
- Kept the change small: no architecture changes, no new dependencies, and no selector features beyond the specified bounded OR terms.

## Concerns

- Final broader database-backed regression and a clean migration-state check remain unverified after the last stale expectation correction because the user requested no further database/network waiting at the checkpoint. The focused GREEN run before that correction was successful, and the remaining edit only changes expected `asset_count` from `4` to `3` in the already-failing assertion.

## Fix round 1

### Implementation

- Added nested selector-term key validation in `_validated_selector_term()`. Each bounded OR term now accepts only `asset_types` and `labels`, matching the documented selector contract.
- Added `test_resolve_scope_rejects_unsupported_nested_selector_term_keys`, which verifies a nested `unsupported` key raises `UnsupportedAssetSelector`.

### RED and GREEN evidence

The focused regression was added before the production change. With controlled local PostgreSQL access, it initially failed as expected:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/domain/test_inspection_scope.py -q -k unsupported_nested_selector_term_keys
FAILED test_resolve_scope_rejects_unsupported_nested_selector_term_keys
Failed: DID NOT RAISE <class 'apps.inspections.services.scope.UnsupportedAssetSelector'>
1 failed, 6 deselected in 2.10s
```

After the validator change, the same command passed:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/domain/test_inspection_scope.py -q -k unsupported_nested_selector_term_keys
1 passed, 6 deselected in 1.61s
```

### Required database-backed reruns

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests -q -k "scope or resource_type or manual_inspection"
35 passed, 367 deselected in 5.20s

DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python manage.py makemigrations --check
No changes detected
```

### Self-review

- Confirmed the nested key check runs before any term fields are read, so unsupported values cannot be silently ignored.
- Confirmed the change preserves the legacy single-selector and valid bounded OR-term paths.
- Confirmed the required database-backed filtered suite and migration-state check were rerun after the stale expectation correction and this fix.

### Concerns

- None. The unrelated untracked `homepage-16-9.png` remains excluded from this fix commit.
