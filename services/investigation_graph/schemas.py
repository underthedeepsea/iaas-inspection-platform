"""Provider-neutral, serialisable contracts for investigation graph state."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolRequest(BaseModel):
    """A model-requested capability invocation after gateway parsing."""

    model_config = ConfigDict(extra="forbid")

    capability_id: str = Field(min_length=1, max_length=192)
    arguments: dict[str, Any]
    reason: str = Field(min_length=1, max_length=2000)


class FinalAnswer(BaseModel):
    """The small answer shape accepted from a provider's FINAL action."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0, le=1)


class Evidence(BaseModel):
    """Bounded, persistence-ready evidence without raw provider payloads."""

    model_config = ConfigDict(extra="forbid")

    evidence_key: str = Field(min_length=1, max_length=192)
    summary: str = Field(min_length=1, max_length=4000)
    payload: dict[str, Any]
    source: str = Field(min_length=1, max_length=128)
    capability_id: str = Field(min_length=1, max_length=192)
    confidence: float = Field(default=1.0, ge=0, le=1)
    materiality: float = Field(default=0.0, ge=0, le=1)


class ToolCallHistory(BaseModel):
    """Safe call metadata suitable for Task 12 persistence."""

    model_config = ConfigDict(extra="forbid")

    capability_id: str = Field(min_length=1, max_length=192)
    arguments: dict[str, Any]
    reason: str = Field(default="", max_length=2000)
    status: str = Field(min_length=1, max_length=32)
    outcome: str = Field(min_length=1, max_length=32)
    error_code: str = Field(default="", max_length=64)
    evidence_key: str = Field(default="", max_length=192)


class FinalResult(BaseModel):
    """Stable public result returned by every graph termination path."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["RESOLVED", "UNRESOLVED", "FAILED"]
    summary: str
    conclusion: str
    facts: list[str]
    next_steps: list[str]
    confidence: float = Field(default=0.0, ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    tool_history: list[ToolCallHistory] = Field(default_factory=list)
    rounds_used: int = Field(default=0, ge=0)
    tool_calls_used: int = Field(default=0, ge=0)


# Descriptive aliases keep the graph API convenient for callers that use the
# terminology from section 52 of the design document.
CallToolSchema = ToolRequest
FinalSchema = FinalAnswer
EvidenceSchema = Evidence
InvestigationResult = FinalResult


def model_dump(value: BaseModel) -> dict[str, Any]:
    """Use one Pydantic-version-neutral dump helper for graph state."""

    return value.model_dump(mode="json")
