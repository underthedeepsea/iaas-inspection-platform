from django.db import migrations


RETIRED_CODES = (
    "topology.control_plane_anti_affinity",
    "llm.ttft_slo",
    "llm.queue_backlog",
)


def retire_demo_plugins(apps, schema_editor):
    Item = apps.get_model("inspections", "InspectionItem")
    Binding = apps.get_model("inspections", "InspectionItemResourceType")
    Item.objects.filter(code__in=RETIRED_CODES).update(enabled=False)
    Binding.objects.filter(inspection_item__code__in=RETIRED_CODES).update(enabled=False)


class Migration(migrations.Migration):
    dependencies = [("inspections", "0011_inspection_item_rule_config")]
    operations = [migrations.RunPython(retire_demo_plugins, migrations.RunPython.noop)]
