from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0014_add_clustering_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="DiscoveryStats",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("stats", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "discovery_stats",
                "ordering": ["-created_at"],
            },
        ),
        migrations.RemoveIndex(
            model_name="dashboardbgc",
            name="idx_db_assembly_novelty",
        ),
        migrations.AddIndex(
            model_name="dashboardbgc",
            index=models.Index(fields=["assembly", "-novelty_score"], name="idx_db_assembly_novelty"),
        ),
    ]
