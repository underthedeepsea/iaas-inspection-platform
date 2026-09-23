from .inference_performance import check_inference_performance
from .plugin import RuleDefinition


class UnsupportedInspectionRule(ValueError):
    pass


CODE_PLUGINS = {
    'llm.performance_profile': RuleDefinition(
        rule_code='llm.performance_profile', name='推理性能画像', rule_version='1.0.0',
        plugin_id='inference-performance', plugin_version='1.0.0', operation_key='evaluate',
        resource_types=('LLM_RUNTIME',), handler=check_inference_performance,
        parameters={}, input_source='INFERENCE_SNAPSHOT',
        description='基于真实推理快照的固定阈值、动态基线与趋势评估。',
    ),
}
RULES = {code: plugin.handler for code, plugin in CODE_PLUGINS.items()}


def get_code_plugin(code):
    try:
        return CODE_PLUGINS[code]
    except KeyError:
        raise UnsupportedInspectionRule(code) from None


def list_code_plugins():
    return tuple(CODE_PLUGINS.values())


def list_rules():
    return list_code_plugins()


def get_rule(code):
    return get_code_plugin(code).handler
