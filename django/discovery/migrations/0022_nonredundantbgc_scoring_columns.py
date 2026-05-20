"""Add missing scoring/projection columns to NonRedundantBGC.

The model gained ``umap_projected``, ``novelty_score`` and ``domain_novelty``
but no migration was generated for them, so the columns are absent on
already-deployed databases. This migration restores parity with the model.

Uses ``ADD COLUMN IF NOT EXISTS`` so it is safe on databases where the columns
were already created by an earlier (now-removed) migration. Django state is
kept in sync via ``SeparateDatabaseAndState``.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0021_bgcdomain_interpro_entry_and_go_terms"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "discovery_non_redundant_bgc" '
                        'ADD COLUMN IF NOT EXISTS "umap_projected" boolean DEFAULT false NOT NULL;'
                        'ALTER TABLE "discovery_non_redundant_bgc" '
                        'ADD COLUMN IF NOT EXISTS "novelty_score" double precision NULL;'
                        'ALTER TABLE "discovery_non_redundant_bgc" '
                        'ADD COLUMN IF NOT EXISTS "domain_novelty" double precision NULL;'
                    ),
                    reverse_sql=(
                        'ALTER TABLE "discovery_non_redundant_bgc" '
                        'DROP COLUMN IF EXISTS "domain_novelty";'
                        'ALTER TABLE "discovery_non_redundant_bgc" '
                        'DROP COLUMN IF EXISTS "novelty_score";'
                        'ALTER TABLE "discovery_non_redundant_bgc" '
                        'DROP COLUMN IF EXISTS "umap_projected";'
                    ),
                ),
            ],
            state_operations=[
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
            ],
        ),
    ]
