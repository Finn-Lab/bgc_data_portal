"""Add missing scoring/projection columns to NonRedundantBGC.

The model gained ``umap_projected``, ``novelty_score`` and ``domain_novelty``
but no migration was generated for them, so the columns are absent on
already-deployed databases. This migration restores parity with the model.
All three additions are nullable / have literal defaults, so the backfill is
safe on populated tables.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0021_bgcdomain_interpro_entry_and_go_terms"),
    ]

    operations = [
        migrations.AddField(
            model_name="nonredundantbgc",
            name="umap_projected",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="nonredundantbgc",
            name="novelty_score",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="nonredundantbgc",
            name="domain_novelty",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
