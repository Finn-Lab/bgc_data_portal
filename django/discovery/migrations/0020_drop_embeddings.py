"""Destructive removal of the ESM embedding stack.

Drops:
  - ``BgcEmbedding`` model + ``discovery_bgc_embedding`` table + HNSW index
  - ``ProteinEmbedding`` model + ``discovery_protein_embedding`` table + HNSW index
  - ``DashboardBgc.nearest_validated_accession``
  - ``DashboardBgc.nearest_validated_distance``

The composite-Dice scoring path (see ``discovery.services.clustering.nrb_scoring``)
fully supersedes the retired functionality.

Irreversible without re-vectorising every BGC and protein.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        # Pin to the migration that introduced NRB scoring fields. The dev
        # team's ``makemigrations`` may have inserted intermediate migrations
        # (e.g. ``0019_*``); list this one after them when applying.
        ("discovery", "0018_domain_clustering"),
    ]

    operations = [
        # Drop HNSW indexes explicitly so the table drop doesn't trip on
        # opclass references in older Postgres versions.
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_bgc_emb_hnsw;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_prot_emb_hnsw;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.DeleteModel(name="BgcEmbedding"),
        migrations.DeleteModel(name="ProteinEmbedding"),
        migrations.RemoveField(
            model_name="DashboardBgc",
            name="nearest_validated_accession",
        ),
        migrations.RemoveField(
            model_name="DashboardBgc",
            name="nearest_validated_distance",
        ),
    ]
