from django.db import migrations


RESOURCE_TYPES = (
    ("CONTROL_PLANE", "控制面", "control", ("POD",), 10),
    ("KVM_CLUSTER", "KVM 集群", "cluster", ("CLUSTER",), 20),
    ("K8S_CLUSTER", "Kubernetes 集群", "cluster", ("CLUSTER",), 30),
    ("LLM_RUNTIME", "LLM 推理引擎", "llm", ("LLM_INSTANCE",), 40),
    ("GPU_POOL", "GPU 资源", "gpu", ("GPU",), 50),
    ("HOST", "主机基础环境", "host", ("HOST",), 60),
)


def seed_resource_types(apps, schema_editor):
    resource_type_model = apps.get_model("inspections", "ResourceType")
    for code, name, icon, asset_types, sort_order in RESOURCE_TYPES:
        resource_type_model.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "icon": icon,
                "asset_selector": {"asset_types": list(asset_types)},
                "enabled": True,
                "sort_order": sort_order,
            },
        )


def unseed_resource_types(apps, schema_editor):
    resource_type_model = apps.get_model("inspections", "ResourceType")
    resource_type_model.objects.filter(
        code__in=[code for code, *_ in RESOURCE_TYPES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("inspections", "0003_resourcetype_inspectionitemresourcetype_and_more")]
    operations = [migrations.RunPython(seed_resource_types, unseed_resource_types)]
