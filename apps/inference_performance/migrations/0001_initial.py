import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="InferencePerformanceSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source", models.CharField(max_length=64)),
                ("sample_id", models.CharField(max_length=192)),
                ("engine_id", models.CharField(max_length=192)),
                ("engine_type", models.CharField(max_length=32)),
                ("model_name", models.CharField(max_length=256)),
                ("window_start", models.DateTimeField()),
                ("window_end", models.DateTimeField(db_index=True)),
                ("metrics", models.JSONField(default=dict)),
                ("evaluation", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("environment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="core.environment")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["environment", "engine_id", "window_end"], name="idx_inf_perf_engine_time"),
                    models.Index(fields=["engine_type", "model_name", "window_end"], name="idx_inf_perf_model_time"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("source", "sample_id"), name="uq_inference_perf_source_sample"),
                ],
            },
        ),
    ]
