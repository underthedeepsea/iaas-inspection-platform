from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleDefinition:
    rule_code: str
    name: str
    rule_version: str
    plugin_id: str
    plugin_version: str
    operation_key: str
    resource_types: tuple[str, ...]
    handler: Callable
    parameters: dict
    status: str = 'ACTIVE'
    description: str = ''
    engine: str = 'PYTHON_RULE'

    @property
    def version(self):
        return self.plugin_version

    @property
    def inspection_item_code(self):
        return self.rule_code


# Kept for import compatibility while the public concept is now RuleDefinition.
CodePluginDefinition = RuleDefinition
