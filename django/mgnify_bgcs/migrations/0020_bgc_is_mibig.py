from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mgnify_bgcs', '0019_assembly_genome_quality_assembly_genome_size_mb_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='bgc',
            name='is_mibig',
            field=models.BooleanField(default=False),
        ),
    ]
