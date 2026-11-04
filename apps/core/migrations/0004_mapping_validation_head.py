from django.db import migrations,models
import django.db.models.deletion
class Migration(migrations.Migration):
    dependencies=[('core','0003_mapping_local_loop')]
    operations=[migrations.AddField(model_name='mappingbundle',name='latest_validation',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='validated_bundle_heads',to='core.mappingvalidation'))]
