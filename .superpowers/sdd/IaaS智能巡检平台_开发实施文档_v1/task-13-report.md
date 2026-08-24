# Task 13 report: Human feedback and Experience-to-Code

## Scope

Implemented the Task 13 domain services without adding duplicate models or a
new model app. `HumanFeedback` remains in `apps.investigations`, while
`Experience`, `ExperienceEvidence`, `CodeizationTask`, and all Capability
models remain the existing persisted models.

## RED / GREEN evidence

The focused tests were written before the new service packages existed. The
first database-enabled run failed as expected with six `ModuleNotFoundError`
failures for `apps.feedback` / `apps.experiences`.

After the minimal implementation and fixes, the focused suite is green:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q \
  tests/domain/test_feedback_experience.py
......                                                                   [100%]
6 passed in 1.35s
```

The initial sandboxed attempt could not connect to local PostgreSQL
(`Operation not permitted`); the RED run above used the approved local
database connection and proves the intended missing-package failure.

## Implementation

- `apps/feedback/services.py`: explicit-actor feedback persistence, enum and
  rating validation, environment/risk/investigation/conversation/message/
  evidence context consistency, HELPFUL-only persistence, and opt-in
  `CONFIRMED_ROOT_CAUSE` Experience creation.
- `apps/experiences/services.py`: stable `feedback:<feedback UUID>` Experience
  identity, idempotent `DISCOVERED` creation, evidence links, locked
  confirmation, canonical target claims, and `CODE_PENDING` task creation
  after confirmation.
- `apps/experiences/codeization.py`: row-locked
  `CODE_PENDING -> SHADOW -> CODE_ACTIVE` transitions, candidate-to-SHADOW and
  SHADOW-to-ACTIVE CapabilityVersion gates, read-only/claim/version checks,
  resolver binding management, current-version replacement, InspectionItem
  code status/coverage/resolved claims, and terminal task/Experience updates.
- `tests/domain/test_feedback_experience.py`: focused domain coverage for
  HELPFUL, idempotent Experience creation, confirmation/task separation,
  state transitions, registry resolution, cross-environment rejection, and
  illegal backtracking/direct activation.

No source code is generated or executed by codeization. REST/API/auth and
platform-admin authorization remain Task 14 scope.

## Verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q
214 passed in 14.34s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

/Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m compileall -q apps services config tests
git diff --check
```

No migration is required: this task only adds service packages and tests.

## Concerns

- The existing models do not have a dedicated confirmation-actor or
  codeization-actor field; feedback preserves the authenticated user and task
  owner preserves the actor username for later audit integration.
- The services intentionally do not expose REST views or authorization policy;
  those belong to Task 14.
