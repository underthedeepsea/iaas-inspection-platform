import pytest

from apps.inspections.rules import registry
from apps.inspections.rules.inference_performance import check_inference_performance


def test_only_real_inference_plugin_is_active_with_stable_metadata():
    plugin = registry.get_code_plugin('llm.performance_profile')
    assert (plugin.plugin_id, plugin.version, plugin.engine, plugin.resource_types, plugin.input_source) == (
        'inference-performance', '1.0.0', 'PYTHON_RULE', ('LLM_RUNTIME',), 'INFERENCE_SNAPSHOT',
    )
    assert plugin.handler is check_inference_performance
    assert registry.get_rule('llm.performance_profile') is plugin.handler
    assert {entry.rule_code for entry in registry.list_code_plugins()} == {'llm.performance_profile'}
    for retired in ('llm.ttft_slo', 'llm.queue_backlog', 'topology.control_plane_anti_affinity'):
        with pytest.raises(registry.UnsupportedInspectionRule):
            registry.get_code_plugin(retired)
