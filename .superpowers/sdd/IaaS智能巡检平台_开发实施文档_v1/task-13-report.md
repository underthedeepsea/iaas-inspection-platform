# Task 13 report: Human feedback and Experience-to-Code

## Scope

Task 13 uses the existing `HumanFeedback`, `Experience`, `ExperienceEvidence`,
`CodeizationTask`, `InspectionItem`, Capability, and binding models. It adds
domain services only; no duplicate model app and no source-code generation or
execution were introduced.

## Fix Round 1 RED / GREEN evidence

The reviewer regression tests were added before the corresponding fixes. The
first database-enabled Fix Round 1 run was RED with 9 failures (old resolver
retirement/item downgrade, partial/current Registry lookup, shared replacement,
thresholds, retry ordering, actor/boolean validation, audit writes, and
concurrent retry). The focused suite is now GREEN:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q \
  tests/domain/test_feedback_experience.py tests/services/test_capability_registry.py
25 passed in 2.09s
```

Additional RED/GREEN regression checks covered the `applicable_scope` guard,
strict persisted `create_experience` typing, and audit transition payloads.

## Implementation

- `apps/feedback/services.py`: explicit authenticated actor, exact boolean
  validation, context/environment consistency, HELPFUL-only Experience
  behavior, and transactional feedback audit plus opt-in root-cause
  Experience creation.
- `apps/experiences/services.py`: explicit-actor/idempotent conversion,
  locked confirmation and task creation, canonical claims, scope validation,
  evidence links, and same-transaction audit events.
- `apps/experiences/codeization.py`: row-locked
  `CODE_PENDING -> SHADOW -> CODE_ACTIVE` transitions, candidate/version
  identity and read-only checks, SHADOW retry idempotency before candidate
  validation, aggregate item status derivation, shared-capability fail-closed
  replacement, and transition audits. Shadow activation thresholds are the
  project constants `shadow_cases >= 3`, `precision >= 0.8`, and
  `critical_false_positive == 0`; a new version cannot skip SHADOW.
- `services/plugin_runtime/registry.py`: formal resolver lookup requires an
  enabled binding, enabled item, ACTIVE capability version equal to the exact
  `Capability.current_version`, and covered claim eligibility for partial
  items. Shadow lookup does not require aggregate item status SHADOW.
- `apps/audits/services.py`: bounded non-sensitive audit payload boundary.
- Tests cover old-resolver survival, partial claims, shared replacement and
  rollback, threshold boundaries, idempotent/concurrent SHADOW retry, actor
  and boolean guards, context consistency, and audit rows.

REST/API/auth remains Task 14 scope. Services accept the explicit actor and do
not generate or execute source code.

## Verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q
225 passed in 16.09s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

/Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m compileall -q apps services config tests
git diff --check
```

No migration is required: this round changes service code, tests, fixtures,
and the report only.

## Risks / follow-up

- The existing models have no dedicated transition-actor columns; audit rows
  preserve the authenticated actor, environment, object identity, and safe
  transition metadata.
- REST authorization and API serializers remain Task 14 responsibilities.
