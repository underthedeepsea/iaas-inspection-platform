from django.db import migrations, models


RISK_STATUS_CHOICES = [
    ("NEW", "New"),
    ("PERSISTING", "Persisting"),
    ("WORSENED", "Worsened"),
    ("INVESTIGATING", "Investigating"),
    ("LOCATED", "Located"),
    ("PENDING_ACTION", "Pending action"),
    ("IN_PROGRESS", "In progress"),
    ("PENDING_REVERIFY", "Pending reverification"),
    ("RECOVERED", "Recovered"),
    ("IGNORED", "Ignored"),
    ("FALSE_POSITIVE", "False positive"),
]

# Legacy values were used by the initial schema before the lifecycle states
# were introduced.  These mappings preserve their operational meaning while
# keeping every row valid before the choices are narrowed below.
RISK_FORWARD_STATUS_MAPPING = {
    "ACTIVE": "PERSISTING",
    "ACKNOWLEDGED": "INVESTIGATING",
    "MITIGATING": "IN_PROGRESS",
    "CLOSED": "RECOVERED",
    "INVALID": "FALSE_POSITIVE",
}
OBSERVATION_FORWARD_STATUS_MAPPING = {
    "ACTIVE": "PERSISTING",
    "ACKNOWLEDGED": "INVESTIGATING",
    "MITIGATING": "IN_PROGRESS",
    "CLOSED": "RECOVERED",
    "INVALID": "FALSE_POSITIVE",
}

# Reverse mappings deliberately collapse new-only states to the nearest
# status in each model's 0001 vocabulary.  RECOVERED stays RECOVERED; it is
# never rewritten to legacy CLOSED.
RISK_REVERSE_STATUS_MAPPING = {
    "NEW": "NEW",
    "PERSISTING": "ACTIVE",
    "WORSENED": "ACTIVE",
    "INVESTIGATING": "ACKNOWLEDGED",
    "LOCATED": "ACKNOWLEDGED",
    "PENDING_ACTION": "MITIGATING",
    "IN_PROGRESS": "MITIGATING",
    "PENDING_REVERIFY": "MITIGATING",
    "RECOVERED": "RECOVERED",
    "IGNORED": "INVALID",
    "FALSE_POSITIVE": "INVALID",
}
OBSERVATION_REVERSE_STATUS_MAPPING = {
    "NEW": "NEW",
    "PERSISTING": "ACTIVE",
    "WORSENED": "ACTIVE",
    "INVESTIGATING": "ACKNOWLEDGED",
    "LOCATED": "ACKNOWLEDGED",
    "PENDING_ACTION": "MITIGATING",
    "IN_PROGRESS": "MITIGATING",
    "PENDING_REVERIFY": "MITIGATING",
    "RECOVERED": "RECOVERED",
    "IGNORED": "INVALID",
    "FALSE_POSITIVE": "INVALID",
}

# Kept as the compatibility name used by callers of the first migration.
LEGACY_STATUS_MAPPING = RISK_FORWARD_STATUS_MAPPING
REVERSE_STATUS_MAPPING = RISK_REVERSE_STATUS_MAPPING


def _migrate_legacy_statuses(apps, schema_editor):
    risk_model = apps.get_model("risks", "Risk")
    observation_model = apps.get_model("risks", "RiskObservation")
    history_model = apps.get_model("risks", "RiskStatusHistory")
    for old_status, new_status in RISK_FORWARD_STATUS_MAPPING.items():
        risk_model.objects.filter(status=old_status).update(status=new_status)
        history_model.objects.filter(from_status=old_status).update(from_status=new_status)
        history_model.objects.filter(to_status=old_status).update(to_status=new_status)
    for old_status, new_status in OBSERVATION_FORWARD_STATUS_MAPPING.items():
        observation_model.objects.filter(status_after=old_status).update(status_after=new_status)


def _restore_legacy_statuses(apps, schema_editor):
    risk_model = apps.get_model("risks", "Risk")
    observation_model = apps.get_model("risks", "RiskObservation")
    history_model = apps.get_model("risks", "RiskStatusHistory")
    for new_status, old_status in RISK_REVERSE_STATUS_MAPPING.items():
        risk_model.objects.filter(status=new_status).update(status=old_status)
        history_model.objects.filter(from_status=new_status).update(from_status=old_status)
        history_model.objects.filter(to_status=new_status).update(to_status=old_status)
    for new_status, old_status in OBSERVATION_REVERSE_STATUS_MAPPING.items():
        observation_model.objects.filter(status_after=new_status).update(status_after=old_status)


class Migration(migrations.Migration):

    dependencies = [
        ("risks", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_migrate_legacy_statuses, _restore_legacy_statuses),
        migrations.AlterField(
            model_name="risk",
            name="status",
            field=models.CharField(
                choices=RISK_STATUS_CHOICES,
                db_index=True,
                default="NEW",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="riskobservation",
            name="status_after",
            field=models.CharField(
                choices=RISK_STATUS_CHOICES,
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="riskstatushistory",
            name="from_status",
            field=models.CharField(
                blank=True,
                choices=RISK_STATUS_CHOICES,
                max_length=32,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="riskstatushistory",
            name="to_status",
            field=models.CharField(
                choices=RISK_STATUS_CHOICES,
                db_index=True,
                max_length=32,
            ),
        ),
    ]
