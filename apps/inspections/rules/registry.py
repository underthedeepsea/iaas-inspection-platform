from .control_plane_anti_affinity import check_control_plane_anti_affinity
from .llm_ttft_slo import check_llm_ttft_slo
from .llm_queue_backlog import check_llm_queue_backlog
from .plugin import RuleDefinition


class UnsupportedInspectionRule(ValueError):
    pass


CODE_PLUGINS = {
    'topology.control_plane_anti_affinity': RuleDefinition(
        rule_code='topology.control_plane_anti_affinity', name='控制面反亲和', rule_version='1.0.0',
        plugin_id='control-plane-anti-affinity', plugin_version='1.0.0', operation_key='evaluate',
        resource_types=('CONTROL_PLANE',), handler=check_control_plane_anti_affinity,
        parameters={'replica_group_labels': ['replica_group', 'anti_affinity'], 'cluster_field': 'topology.cluster', 'min_replicas': 2},
        description='按集群与副本组边界检查控制面 Pod 是否分散在不同主机。',
    ),
    'llm.ttft_slo': RuleDefinition(
        rule_code='llm.ttft_slo', name='LLM TTFT SLO', rule_version='1.0.0',
        plugin_id='llm-ttft-slo', plugin_version='1.0.0', operation_key='evaluate',
        resource_types=('LLM_RUNTIME',), handler=check_llm_ttft_slo,
        parameters={'metric': 'ttft_ms', 'threshold_ms': 180, 'min_samples': 3, 'percentile': 95},
        description='使用 nearest-rank 计算首 Token 延迟 P95，并与阈值比较。',
    ),
    'llm.queue_backlog': RuleDefinition(
        rule_code='llm.queue_backlog', name='LLM 最近 N 点连续超限', rule_version='1.0.0',
        plugin_id='llm-queue-backlog', plugin_version='1.0.0', operation_key='evaluate',
        resource_types=('LLM_RUNTIME',), handler=check_llm_queue_backlog,
        parameters={'metric': 'queue_depth', 'threshold': 10, 'consecutive_points': 3},
        description='检查最近 N 个队列采样点是否全部连续超过阈值，不推断真实时间连续性。',
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
