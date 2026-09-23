from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0001_initial"),
        ("inference_performance", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="inferenceperformancesnapshot",
            name="asset",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="performance_snapshots", to="assets.asset"),
        ),
        migrations.AddIndex(
            model_name="inferenceperformancesnapshot",
            index=models.Index(fields=["asset", "window_end"], name="idx_inf_perf_asset_time"),
        ),
    ]
