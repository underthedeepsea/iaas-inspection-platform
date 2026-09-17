import pytest

from apps.inspections.rules import registry
from apps.inspections.rules.llm_ttft_slo import check_llm_ttft_slo


def test_launch_plugins_have_stable_metadata_and_compatible_handlers():
    assert hasattr(registry, 'get_code_plugin')
    plugin = registry.get_code_plugin('llm.ttft_slo')
    assert (plugin.plugin_id, plugin.version, plugin.engine, plugin.resource_types) == ('llm-ttft-slo', '1.0.0', 'PYTHON_RULE', ('LLM_RUNTIME',))
    assert plugin.handler is check_llm_ttft_slo
    assert registry.get_rule('llm.ttft_slo') is plugin.handler
    assert {p.inspection_item_code for p in registry.list_code_plugins()} == {'llm.ttft_slo', 'llm.queue_backlog', 'topology.control_plane_anti_affinity'}
    with pytest.raises(registry.UnsupportedInspectionRule):
        registry.get_code_plugin('missing')
