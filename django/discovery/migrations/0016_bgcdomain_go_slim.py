from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0015_discoverystats_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="bgcdomain",
            name="go_slim",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
