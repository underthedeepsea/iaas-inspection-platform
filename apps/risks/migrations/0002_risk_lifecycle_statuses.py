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


class Migration(migrations.Migration):

    dependencies = [
        ("risks", "0001_initial"),
    ]

    operations = [
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
