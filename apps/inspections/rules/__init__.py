from .plugin import CodePluginDefinition, RuleDefinition
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CheckResultSpec:
    asset: object
    status: str
    summary: str
    observed_value: dict = field(default_factory=dict)
    expected_value: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    severity: str | None = None
