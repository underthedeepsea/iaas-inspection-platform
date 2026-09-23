"""Whitelisted invocation of registered deterministic CODE rules."""

from apps.inspections.rules.registry import get_code_plugin


def dispatch_code_rule(*, rule_code, reader, assets, config):
    plugin = get_code_plugin(rule_code)
    if getattr(reader, 'source_type', None) != plugin.input_source:
        raise ValueError(f'input source does not match registered rule {rule_code}')
    return plugin.handler(reader=reader, assets=assets, config=config)
