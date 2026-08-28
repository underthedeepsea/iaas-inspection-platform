"""Deterministic model gateway used by local and CI browser acceptance tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .base import (
    CallToolAction,
    FinalAction,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    coerce_request,
    configured_value,
)


class FakeProvider(ModelGateway):
    """Return one safe tool call followed by a deterministic final answer.

    The provider reads only the bounded JSON envelope produced by the graph.
    It is intentionally not a general-purpose mock of model behaviour: its
    purpose is to make the real browser path exercise capability admission,
    execution, evidence persistence, and event streaming without a network
    model dependency.
    """

    provider_name = "fake"

    def __init__(self):
        self.model = str(configured_value("FAKE_MODEL", "e2e-deterministic"))
        self.capability_id = str(
            configured_value("FAKE_CAPABILITY_ID", "e2e.llm.scheduler.pressure")
        )
        self.asset_id = str(configured_value("FAKE_ASSET_ID", "llm-0"))

    def invoke(self, request: ModelRequest) -> ModelResponse:
        request = coerce_request(request)
        envelope = _request_envelope(request)
        context = envelope.get("context") if isinstance(envelope.get("context"), Mapping) else {}
        evidence = envelope.get("evidence") if isinstance(envelope.get("evidence"), list) else []
        claim = context.get("missing_claim")

        if claim and not evidence:
            action = CallToolAction(
                capability_id=self.capability_id,
                arguments={"asset_id": self.asset_id},
                reason="Collect the deterministic read-only evidence for the missing claim.",
            )
        else:
            action = FinalAction(
                summary="基于确定性只读证据完成 AI 研判。",
                confidence=0.92 if evidence else 0.7,
            )
        return ModelResponse(
            action=action,
            model=self.model,
            provider=self.provider_name,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            metadata={"token_source": "estimated"},
        )


def _request_envelope(request: ModelRequest) -> dict[str, Any]:
    for message in reversed(request.messages):
        if not isinstance(message, Mapping) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            value = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(value) if isinstance(value, Mapping) else {}
    return {}


__all__ = ["FakeProvider"]
