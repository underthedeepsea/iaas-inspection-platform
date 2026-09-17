# Task 5: Separate Investigation JSON History from SSE

## Backend slice

### Implementation

- Added a dedicated `investigation_event_stream` API view for replayable SSE.
- Routed `/investigations/<id>/events` to the existing bounded JSON projection.
- Added `/investigations/<id>/events/stream` routes in both actual route owners: `apps/inspections/urls.py` (the route reached first by `apps/api/urls.py`) and `apps/investigations/public_urls.py`.
- Preserved viewer ownership checks, `Last-Event-ID` validation, terminal stream closure, and the existing public event serializer.
- Updated resource-investigation creation responses to advertise the stream URL.
- Kept `investigation_events` as a compatibility alias for the stream view.

### TDD RED

Added JSON-history and SSE-stream contract tests before the route split:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/api/test_resource_investigation_api.py -q -k "events_returns_json_history or event_stream_returns_sse"
FF
2 failed, 6 deselected
JSON endpoint returned text/event-stream instead of application/json.
Stream endpoint returned 404.
```

### TDD GREEN and verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests -q -k "investigation and event"
7 passed, 397 deselected

DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/api/test_resource_investigation_api.py tests/api/test_investigation_public_api.py tests/api/test_sse_resume.py -q
20 passed

git diff --check
passed
```

### Files changed

- `apps/investigations/api.py`
- `apps/investigations/public_urls.py`
- `apps/inspections/urls.py`
- `tests/api/test_resource_investigation_api.py`

### Self-review and concerns

- The JSON history path uses the existing owner-scoped projection and keeps pagination behavior.
- The SSE path retains replay from `Last-Event-ID` and closes on analysis terminal events or terminal investigation status.
- Existing resource-investigation tests now assert the split content types and stream path.
- The frontend slice still needs to move history/stream helpers into `investigationEvents.ts` and add the replay/live deduplication regression.

### Commit

`2554e24 fix: split investigation history and event stream routes`

## Frontend slice

### Implementation

- Added `frontend/src/api/investigationEvents.ts` with the JSON history fetcher and `/events/stream` URL builder.
- Updated `useInvestigationStream` to fetch history from `/events`, subscribe to `/events/stream`, and retain sequence-based replay/live deduplication.
- Kept compatibility exports in `investigations.ts` while moving the implementation to the dedicated event API module.

### TDD RED

Added the replay/live merge test before changing the frontend contract:

```text
npm test -- useInvestigationStream
1 failed
Expected: /api/v1/investigations/investigation-1/events/stream
Received: /api/v1/investigations/investigation-1/events
```

### TDD GREEN and verification

```text
npm test -- useInvestigationStream
1 test passed

npm test -- AIAnalysisPanel useInvestigationStream
2 test files, 4 tests passed

npm test
23 test files, 48 tests passed

npm run build
TypeScript check and Vite build passed

git diff --check
passed
```

The full frontend test run retains existing Node/jsdom warnings; Vitest exited successfully. The build retains the existing chunk-size warning.

### Files changed

- `frontend/src/api/investigations.ts`
- `frontend/src/api/investigationEvents.ts`
- `frontend/src/features/ai-analysis/useInvestigationStream.ts`
- `frontend/src/features/ai-analysis/useInvestigationStream.test.ts`

### Self-review and concerns

- History events are normalized through the dedicated API module, while live events keep the existing terminal handling and recovery behavior.
- The sequence map ensures history `1,2` plus live `2,3` yields exactly `1,2,3`.
- No backend files were changed in this slice.

### Commit

`0961056 fix: merge investigation history with live stream`

## Review fix round: redact resource investigation SSE payloads

### Finding

- The resource investigation SSE endpoint serialized `InvestigationEvent.payload` directly, bypassing the `_public_json` redaction policy used by JSON `/events` history and allowing sensitive keys and text to leak.

### TDD RED

Added a focused endpoint regression containing a safe value, sensitive keys, and sensitive text, then ran it against the current implementation:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/api/test_resource_investigation_api.py -q -k "event_stream_redacts_payload_with_public_history_policy"
F                                                                        [100%]
=================================== FAILURES ===================================
_ test_resource_investigation_event_stream_redacts_payload_with_public_history_policy _

>       assert envelope["payload"] == {
            "details": {"message": "[redacted]", "note": "safe note"},
            "summary": "safe summary",
        }
E       AssertionError: assert {'api_key': '...safe summary'} == {'details': {...safe summary'}
E         Differing items:
E         {'details': {'authorization': 'Bearer do-not-return', 'message': 'token=do-not-return', 'note': 'safe note'}} != {'details': {'message': '[redacted]', 'note': 'safe note'}}
E         Left contains 1 more item:
E         {'api_key': 'do-not-return'}

tests/api/test_resource_investigation_api.py:162: AssertionError
=========================== short test summary info ============================
FAILED tests/api/test_resource_investigation_api.py::test_resource_investigation_event_stream_redacts_payload_with_public_history_policy
1 failed, 8 deselected in 2.36s
```

### TDD GREEN and verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/api/test_resource_investigation_api.py -q -k "event_stream_redacts_payload_with_public_history_policy"
.                                                                        [100%]
1 passed, 8 deselected in 1.97s

DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python -m pytest tests/api/test_resource_investigation_api.py tests/api/test_investigation_public_api.py tests/api/test_sse_resume.py -q
.....................                                                    [100%]
21 passed in 9.11s

git diff --check
passed
```

### Files changed

- `apps/investigations/api.py`
- `tests/api/test_resource_investigation_api.py`
- `.superpowers/sdd/2026-09-01-v02-final-fix/task-5-report.md`

### Self-review and concerns

- The SSE envelope still exposes the existing `payload` field, now populated through the same `_public_json` function as JSON history.
- Replay cursor/order, owner authorization, `Last-Event-ID` validation, and terminal closure code paths are unchanged.
- No frontend or URL declarations were changed, and `homepage-16-9.png` remains untracked.
- Remaining concern: `_public_json` is a private helper shared across modules; this is intentional to avoid creating a second redaction policy or broadening this focused fix.

### Commit

`fix: redact investigation SSE payloads` (this fix-round commit; exact hash recorded in the completion response)
