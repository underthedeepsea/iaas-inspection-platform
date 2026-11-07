"""Environment-wide collection identity; refuse duplicates before any schema change."""
from django.db import migrations,models
import django.db.models.deletion


def preflight(apps,schema_editor):
    Collection=apps.get_model('core','MappingCollection')
    table=schema_editor.quote_name(Collection._meta.db_table)
    schema_editor.execute(f'LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE')
    duplicate=Collection.objects.using(schema_editor.connection.alias).values('bundle__environment_id','idempotency_key').annotate(total=models.Count('id')).filter(total__gt=1).exists()
    if duplicate:
        raise RuntimeError('Duplicate mapping collection environment/key; migration BLOCKED without modifying existing rows. Resolve by explicit operator decision; no merge/delete/rekey is performed.')


def backfill(apps,schema_editor):
    Collection=apps.get_model('core','MappingCollection')
    Bundle=apps.get_model('core','MappingBundle')
    q=schema_editor.quote_name
    collection=q(Collection._meta.db_table);bundle=q(Bundle._meta.db_table)
    environment=q(Collection._meta.get_field('environment').column)
    bundle_fk=q(Collection._meta.get_field('bundle').column)
    bundle_environment=q(Bundle._meta.get_field('environment').column)
    bundle_pk=q(Bundle._meta.pk.column)
    schema_editor.execute(f'UPDATE {collection} AS c SET {environment}=b.{bundle_environment} FROM {bundle} AS b WHERE c.{bundle_fk}=b.{bundle_pk}')


class Migration(migrations.Migration):
    atomic=True
    dependencies=[('core','0004_mapping_validation_head')]
    operations=[
        migrations.RunPython(preflight,migrations.RunPython.noop),
        migrations.AddField(model_name='mappingcollection',name='environment',field=models.ForeignKey(null=True,on_delete=django.db.models.deletion.PROTECT,to='core.environment')),
        migrations.RunPython(backfill,migrations.RunPython.noop),
        migrations.AlterField(model_name='mappingcollection',name='environment',field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='core.environment')),
        migrations.AddConstraint(model_name='mappingcollection',constraint=models.UniqueConstraint(fields=['environment','idempotency_key'],name='mapping_collection_environment_key')),
        migrations.RemoveConstraint(model_name='mappingcollection',name='mapping_collection_key'),
    ]
