"""Scenario names and the deliberately small set supported by Task 4."""

SCENARIOS = {
    "healthy_baseline": {
        "description": "All generated signals remain within the healthy baseline.",
        "missing_data": (),
    },
    "llm_scheduler_pressure": {
        "description": "TTFT and scheduler queue rise while GPU utilization falls.",
        "missing_data": (),
    },
    "control_plane_anti_affinity": {
        "description": "Two control-plane pods are placed on one host.",
        "missing_data": (),
    },
    "kvm_cluster_baseline": {
        "description": "A healthy KVM cluster fixture.",
        "missing_data": (),
    },
    "k8s_cluster_baseline": {
        "description": "A healthy Kubernetes cluster fixture.",
        "missing_data": (),
    },
    "mixed_resource_inspection": {
        "description": "Control-plane and LLM signals are available together.",
        "missing_data": (),
    },
    "data_incomplete": {
        "description": "The queue metric is absent from the source data.",
        "missing_data": ("queue_depth",),
    },
}

SUPPORTED_SCENARIOS = frozenset(SCENARIOS)


def scenario_config(scenario):
    try:
        return SCENARIOS[scenario]
    except KeyError as exc:
        supported = ", ".join(sorted(SUPPORTED_SCENARIOS))
        raise ValueError(f"Unsupported scenario {scenario!r}; choose one of {supported}") from exc
