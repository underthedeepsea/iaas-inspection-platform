from .control_plane_anti_affinity import check_control_plane_anti_affinity
from .llm_ttft_slo import check_llm_ttft_slo
from .llm_queue_backlog import check_llm_queue_backlog


class UnsupportedInspectionRule(ValueError):
    pass


RULES = {
    'topology.control_plane_anti_affinity': check_control_plane_anti_affinity,
    'llm.ttft_slo': check_llm_ttft_slo,
    'llm.queue_backlog': check_llm_queue_backlog,
}


def get_rule(code):
    try:
        return RULES[code]
    except KeyError:
        raise UnsupportedInspectionRule(code) from None
