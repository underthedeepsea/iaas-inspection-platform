"""Finding specifications and the persistence boundary for executions."""

from dataclasses import dataclass, field

from apps.inspections.models import Finding


@dataclass(frozen=True)
class FindingSpec:
    finding_code: str
    title: str
    category: str
    severity: str
    observed_at: object
    value: dict = field(default_factory=dict)
    source_type: str = Finding.SourceType.RULE
    materiality: float = 0.0
    status: str = Finding.Status.ACTIVE
    asset: object = None


def persist_findings(item_run, finding_specs, *, replace_existing=True):
    """Persist Finding rows for an ``InspectionItemRun``.

    Execution is idempotent at the item-run level.  Replacing the rows scoped
    to that item run keeps a retry from duplicating findings while leaving all
    other inspection results untouched.
    """

    if replace_existing:
        Finding.objects.filter(inspection_item_run=item_run).delete()

    rows = [
        _to_model(item_run, spec)
        for spec in finding_specs
    ]
    if rows:
        Finding.objects.bulk_create(rows)
    return rows


def _to_model(item_run, spec):
    if isinstance(spec, FindingSpec):
        values = spec
    else:
        values = FindingSpec(**spec)
    return Finding(
        inspection_item_run=item_run,
        asset=values.asset,
        finding_code=values.finding_code,
        title=values.title,
        category=values.category,
        severity=values.severity,
        materiality=values.materiality,
        status=values.status,
        value=dict(values.value),
        source_type=values.source_type,
        observed_at=values.observed_at,
    )


# A descriptive alias makes the persistence boundary easy to discover.
save_findings = persist_findings
persist_finding_rows = persist_findings


__all__ = [
    "FindingSpec",
    "persist_finding_rows",
    "persist_findings",
    "save_findings",
]
