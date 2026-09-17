from django.db import migrations


RESOURCE_SELECTORS = {
    "CONTROL_PLANE": {
        "selectors": [
            {"asset_types": ["CLUSTER"], "labels": {"platform": "kubernetes"}},
            {"asset_types": ["HOST"], "labels": {"role": "control-plane"}},
            {"asset_types": ["POD"], "labels": {"component": "control-plane"}},
        ]
    },
    "KVM_CLUSTER": {
        "selectors": [
            {"asset_types": ["CLUSTER"], "labels": {"platform": "kvm"}},
        ]
    },
    "K8S_CLUSTER": {
        "selectors": [
            {"asset_types": ["CLUSTER"], "labels": {"platform": "kubernetes"}},
        ]
    },
    "LLM_RUNTIME": {
        "selectors": [
            {"asset_types": ["LLM_INSTANCE"], "labels": {"workload": "llm"}},
            {"asset_types": ["POD"], "labels": {"workload": "llm"}},
            {"asset_types": ["GPU"], "labels": {"workload": "llm"}},
        ]
    },
    "GPU_POOL": {
        "selectors": [
            {"asset_types": ["GPU"], "labels": {"pool": "gpu"}},
            {"asset_types": ["HOST"], "labels": {"gpu_host": "true"}},
        ]
    },
    "HOST": {
        "selectors": [
            {"asset_types": ["HOST"], "labels": {}},
        ]
    },
}


PREVIOUS_RESOURCE_SELECTORS = {
    "CONTROL_PLANE": {"asset_types": ["CLUSTER", "HOST", "POD"]},
    "KVM_CLUSTER": {"asset_types": ["CLUSTER"], "labels": {"platform": "kvm"}},
    "K8S_CLUSTER": {"asset_types": ["CLUSTER"], "labels": {"platform": "kubernetes"}},
    "LLM_RUNTIME": {"asset_types": ["LLM_INSTANCE", "POD", "GPU"]},
    "GPU_POOL": {"asset_types": ["GPU", "HOST"]},
    "HOST": {"asset_types": ["HOST"]},
}


def update_resource_selectors(apps, schema_editor):
    resource_type_model = apps.get_model("inspections", "ResourceType")
    for code, selector in RESOURCE_SELECTORS.items():
        resource_type_model.objects.filter(code=code).update(asset_selector=selector)


def restore_resource_selectors(apps, schema_editor):
    resource_type_model = apps.get_model("inspections", "ResourceType")
    for code, selector in PREVIOUS_RESOURCE_SELECTORS.items():
        resource_type_model.objects.filter(code=code).update(asset_selector=selector)


class Migration(migrations.Migration):
    dependencies = [("inspections", "0008_v02_scope_and_no_data")]

    operations = [migrations.RunPython(update_resource_selectors, restore_resource_selectors)]
