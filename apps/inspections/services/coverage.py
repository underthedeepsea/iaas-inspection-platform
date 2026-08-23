"""Pure deterministic Claim coverage and AI admission decisions."""

from dataclasses import dataclass

from apps.inspections.models import InspectionItem


@dataclass(frozen=True)
class ClaimCoverage:
    """The persisted coverage decision for one inspection item execution."""

    required_claims: list
    resolved_claims: list
    unresolved_claims: list
    material_claim_gaps: list
    code_coverage_percent: float
    ai_eligible: bool
    data_valid: bool

    @property
    def coverage_percent(self):
        """Compatibility spelling for callers that omit the ``code_`` prefix."""

        return self.code_coverage_percent

    def as_summary(self):
        return {
            "required_claims": list(self.required_claims),
            "resolved_claims": list(self.resolved_claims),
            "unresolved_claims": list(self.unresolved_claims),
            "material_claim_gaps": list(self.material_claim_gaps),
            "code_coverage_percent": self.code_coverage_percent,
            "ai_eligible": self.ai_eligible,
            "data_valid": self.data_valid,
        }


def compute_claim_coverage(
    inspection_item,
    *,
    code_claims=(),
    registry=None,
    data_valid=True,
):
    """Compute required/resolved Claim sets without invoking AI.

    ``code_claims`` is the set established by the deterministic detector.  The
    Task 5 registry is consulted for every candidate Claim; a detector's own
    positive result remains authoritative when no separately registered
    resolver exists.  This keeps the two built-in scenarios code-complete while
    still exposing undeclared Claims as gaps.  A missing or incomplete dataset
    suppresses both code resolution and AI admission.
    """

    if registry is None:
        from services.plugin_runtime.registry import CapabilityRegistry

        registry = CapabilityRegistry()

    required_claims = _unique_claims(getattr(inspection_item, "required_claims", ()))
    deterministic_claims = set(_unique_claims(code_claims))
    candidate_claims = set(deterministic_claims)
    candidate_claims.update(_unique_claims(getattr(inspection_item, "resolved_claims", ())))

    resolved_claims = []
    if data_valid:
        for claim in required_claims:
            if claim not in candidate_claims:
                continue
            if _registry_resolves(registry, claim) or claim in deterministic_claims:
                resolved_claims.append(claim)

    unresolved_claims = [claim for claim in required_claims if claim not in resolved_claims]
    material_claim_gaps = list(unresolved_claims) if data_valid else []
    ai_eligible = bool(material_claim_gaps) and getattr(
        inspection_item, "execution_mode", None
    ) in {
        InspectionItem.ExecutionMode.CODE_FIRST_AI_FALLBACK,
        InspectionItem.ExecutionMode.AI_INVESTIGATION,
    }

    required_count = len(required_claims)
    code_coverage_percent = (
        100.0 if required_count == 0 else round(100 * len(resolved_claims) / required_count, 2)
    )
    return ClaimCoverage(
        required_claims=required_claims,
        resolved_claims=resolved_claims,
        unresolved_claims=unresolved_claims,
        material_claim_gaps=material_claim_gaps,
        code_coverage_percent=code_coverage_percent,
        ai_eligible=ai_eligible,
        data_valid=bool(data_valid),
    )


def _registry_resolves(registry, claim):
    resolver = getattr(registry, "resolve", None)
    if resolver is None:
        return True
    return resolver(claim) is not None


def _unique_claims(claims):
    seen = set()
    result = []
    for claim in claims or ():
        if not isinstance(claim, str) or not claim or claim in seen:
            continue
        seen.add(claim)
        result.append(claim)
    return result


# Keep the vocabulary discoverable for callers that use either verb.
calculate_claim_coverage = compute_claim_coverage
resolve_claim_coverage = compute_claim_coverage
deterministic_coverage = compute_claim_coverage


__all__ = [
    "ClaimCoverage",
    "calculate_claim_coverage",
    "compute_claim_coverage",
    "deterministic_coverage",
    "resolve_claim_coverage",
]
