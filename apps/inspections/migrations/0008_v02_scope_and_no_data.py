from django.db import migrations, models


RESOURCE_SELECTORS = {
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
    for code, selector in RESOURCE_SELECTORS.items():
        asset_types = selector.get("asset_types", [])
        resource_type_model.objects.filter(code=code).update(
            asset_selector={"asset_types": asset_types}
        )


class Migration(migrations.Migration):
    dependencies = [("inspections", "0007_inspectionrunevent_and_more")]

    operations = [
        migrations.AlterField(
            model_name="resourceinspectionsummary",
            name="health_score",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.RunPython(update_resource_selectors, restore_resource_selectors),
    ]
