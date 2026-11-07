import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [
        migrations.CreateModel(name="MappingBundle", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("source_ref", models.CharField(max_length=32)),
            ("cluster_uid", models.CharField(max_length=128)),
            ("monitor_cluster_id", models.CharField(max_length=128)),
            ("head_version", models.PositiveIntegerField(default=0)),
            ("environment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="core.environment")),
        ], options={"db_table": "mapping_bundles"}),
        migrations.CreateModel(name="MappingRevision", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("version", models.PositiveIntegerField()),
            ("schema_version", models.CharField(max_length=32)),
            ("canonical_json", models.TextField()),
            ("content_hash", models.CharField(max_length=64)),
            ("reason", models.CharField(max_length=512)),
            ("actor_label", models.CharField(help_text="Self-described local label; not authenticated identity.", max_length=128)),
            ("bundle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="revisions", to="core.mappingbundle")),
            ("parent_revision", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="children", to="core.mappingrevision")),
            ("rollback_from", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="rollback_children", to="core.mappingrevision")),
        ], options={"db_table": "mapping_revisions"}),
        migrations.AddField(model_name="mappingbundle", name="head_revision", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="headed_bundles", to="core.mappingrevision")),
        migrations.AddConstraint(model_name="mappingbundle", constraint=models.UniqueConstraint(fields=("environment", "source_ref", "cluster_uid"), name="mapping_bundle_scope_uid")),
        migrations.AddConstraint(model_name="mappingbundle", constraint=models.UniqueConstraint(fields=("environment", "source_ref", "monitor_cluster_id"), name="mapping_bundle_scope_monitor")),
        migrations.AddConstraint(model_name="mappingbundle", constraint=models.CheckConstraint(check=models.Q(source_ref="demo-monitor"), name="mapping_bundle_demo_source")),
        migrations.AddConstraint(model_name="mappingbundle", constraint=models.CheckConstraint(check=models.Q(head_version=0, head_revision__isnull=True) | models.Q(head_version__gte=1, head_revision__isnull=False), name="mapping_bundle_head_shape")),
        migrations.AddConstraint(model_name="mappingrevision", constraint=models.UniqueConstraint(fields=("bundle", "version"), name="mapping_revision_sequence")),
        migrations.AddConstraint(model_name="mappingrevision", constraint=models.CheckConstraint(check=models.Q(version__gte=1), name="mapping_revision_positive")),
    ]
