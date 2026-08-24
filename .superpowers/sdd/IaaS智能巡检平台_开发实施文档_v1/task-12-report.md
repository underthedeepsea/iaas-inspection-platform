# Task 12 report: Conversation + SSE recovery (Fix Round 1)

## Scope

Implemented the authenticated conversation/turn/SSE surface from sections 44
and 47. The API reuses the existing `investigations` Conversation,
ConversationMessage, Investigation, InvestigationEvent, ToolCall, and Risk
Evidence models. No queue, worker, thread, Channels layer, or new dependency
was added. Risk-bound conversations always derive `environment` from the
persisted Risk; a client `environment_id` is ignored.

Fix Round 1 closes three reviewer findings: idempotent concurrent turns now
claim a durable Investigation lease before graph execution; Task 11 carries
the exact capability version returned by atomic validation/execution; and the
assistant final/message projection is the bounded eight-field section 47
contract.

## RED / GREEN evidence

The requested tests were written before the conversation production package.
The first sandboxed run could not initialise Django/PostgreSQL because loopback
database access was denied (`OperationalError: ... 127.0.0.1:5432 ... Operation
not permitted`). After allowing local Compose database access, the first
implementation run exposed the expected integration failures:

- the existing development settings did not install Django sessions, so the
  authenticated test client could not use `force_login`;
- `select_related()` plus an unrestricted PostgreSQL `FOR UPDATE` attempted to
  lock the nullable Investigation join;
- the lazy SSE generator returned `200` before owner validation ran;
- deterministic idempotency IDs were not retained on first creation.

Each failure was fixed and rerun. The focused suite is now green:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q \
  tests/api/test_conversation_api.py tests/api/test_sse_resume.py
.............                                                            [100%]
13 passed in 7.20s
```

Fix Round 1 RED/GREEN evidence:

- the new graph regression first failed because terminal tool history had no
  `capability_version_id`;
- the large-final, exact-version, missing-version, and TransactionTestCase
  concurrency regressions were added before their production fixes;
- after the fixes, the focused API/SSE/concurrency suite is green:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q \
  tests/api/test_conversation_api.py tests/api/test_sse_resume.py \
  tests/api/test_conversation_concurrency.py
..................                                                       [100%]
18 passed
```

## Implementation

- `apps/conversations/services.py`: owner-scoped conversation CRUD, Risk
  environment derivation, turn input/Investigation persistence before graph
  execution, injected graph runner, safe terminal projection, Evidence and
  exact-version ToolCall persistence, assistant message creation, event
  sequencing, durable RUNNING claim/recovery, and retry-safe terminal writes.
- `apps/investigations/models.py` plus migration `0004_investigation_claim`:
  persisted claim token and heartbeat fields for short-lived graph ownership.
- `services/investigation_graph/schemas.py` and `nodes.py`: atomic
  `capability_version_id` propagation through selected, succeeded, failed,
  rejected, and budget terminal tool history states.
- `apps/conversations/sse.py`: canonical non-negative `Last-Event-ID` parser
  and ordered PostgreSQL event replay of only `sequence > Last-Event-ID`.
- `apps/conversations/views.py` and `urls.py`: authenticated JSON endpoints and
  `text/event-stream` response with no-store/no-buffering headers.
- `config/urls.py`: `/api/v1/conversations/` routing.
- `config/settings/dev.py`: session and authentication middleware required for
  standard Django authenticated requests.
- `tests/api/test_conversation_api.py`: Risk binding, owner isolation, turn
  persistence, terminal graph error, refresh, optional-key retry, exact
  capability-version, and large-final projection tests.
- `tests/api/test_conversation_concurrency.py`: PostgreSQL
  TransactionTestCase coverage for one graph leader, fast follower, and stale
  claim recovery.
- `tests/api/test_sse_resume.py`: ordering, strict cursor parsing, replay, and
  cross-owner isolation tests.

## Safety and lifecycle invariants

- The graph is invoked after the input transaction commits; final writes occur
  in a separate short transaction.
- A fresh `(conversation, idempotency_key)` claim returns the same 202 turn to
  followers without invoking or waiting for graph/tool work. A conservative
  stale threshold permits recovery after a crashed owner; terminal persistence
  also checks the claim token so an old owner cannot overwrite a recovered
  turn.
- Investigation rows are locked before calculating the next event sequence;
  the existing `(investigation, sequence)` unique constraint remains the final
  guard.
- Every handled graph failure becomes a sanitized `FAILED` Investigation,
  assistant message, and stable `turn.error`; successful and unresolved turns
  end with `turn.completed`.
- Final text, tool history, Evidence payloads, counters, model metadata, and
  SSE payloads are allowlisted/bounded and redact URLs, credentials, raw
  payloads, and sensitive key names. Exception text is never persisted.
- `assistant.final` events and assistant `structured_content` use the direct
  section 47 projection (`summary`, `current_conclusion`, `confidence`,
  `confirmed_facts`, `hypotheses`, `new_evidence`,
  `recommended_next_steps`, `unresolved_questions`). Each field clips
  independently, so required top-level keys survive large valid results.
- ToolCall rows resolve only the graph-provided `capability_version_id`, then
  require matching capability identity, ACTIVE/read-only/current-version
  ownership; missing, malformed, stale, or candidate IDs are skipped closed.
- `idempotency_key`, `turn_key`, or the `Idempotency-Key` header maps to a
  deterministic Investigation UUID. A completed terminal event returns the
  original turn without creating another user or assistant message.
- SSE validates the cursor before querying and resolves owner/event membership
  before returning a streaming response; disconnects do not delete or
  acknowledge rows.

## Verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q
206 passed in 14.18s

DJANGO_SETTINGS_MODULE=config.settings.dev \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

DJANGO_SETTINGS_MODULE=config.settings.dev \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py \
  makemigrations --check --dry-run
No changes detected

/Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m compileall -q apps services config tests
git diff --check
```

The existing schema already contained the required foreign keys, JSON fields,
timestamps, and event sequence uniqueness. Fix Round 1 adds only the two claim
columns in migration `apps/investigations/migrations/0004_investigation_claim.py`.

## Concerns

- The documented model has only one `Conversation.investigation` pointer, so
  historical-turn owner checks use the persisted `conversation_id` in every
  Task 12 event payload; no duplicate conversation model or migration was
  introduced.
- Without an idempotency key/header, two intentionally identical messages are
  treated as separate turns. Clients that need retry identity should send the
  documented optional key.
- A graph history entry without a valid current capability version intentionally
  produces no ToolCall row; its sanitized terminal history remains in the
  terminal event. This is fail-closed behavior for unregistered or candidate
  capabilities, rather than guessing a latest version.
