"""Switch BGC and protein embedding vectors from 1152-dim to 960-dim.

Reflects the change from esmc_600m (layer 29) to esmc_300m (layer 26).
The HNSW indexes must be dropped before the column type can be altered and
then recreated with the new dimension.
"""

import pgvector.django
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0012_protein_embedding_nullable_sha256_unique"),
    ]

    operations = [
        # ── Drop HNSW indexes before altering column dimensions ─────────────
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_bgc_emb_hnsw;",
            reverse_sql=(
                "CREATE INDEX idx_bgc_emb_hnsw ON discovery_bgc_embedding "
                "USING hnsw (vector halfvec_cosine_ops) WITH (m = 16, ef_construction = 512);"
            ),
        ),
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_prot_emb_hnsw;",
            reverse_sql=(
                "CREATE INDEX idx_prot_emb_hnsw ON discovery_protein_embedding "
                "USING hnsw (vector halfvec_cosine_ops) WITH (m = 16, ef_construction = 512);"
            ),
        ),
        # ── Alter column dimensions 1152 → 960 ──────────────────────────────
        migrations.AlterField(
            model_name="bgcembedding",
            name="vector",
            field=pgvector.django.HalfVectorField(dimensions=960),
        ),
        migrations.AlterField(
            model_name="proteinembedding",
            name="vector",
            field=pgvector.django.HalfVectorField(dimensions=960),
        ),
        # ── Recreate HNSW indexes with new dimension ─────────────────────────
        migrations.RunSQL(
            sql=(
                "CREATE INDEX idx_bgc_emb_hnsw ON discovery_bgc_embedding "
                "USING hnsw (vector halfvec_cosine_ops) WITH (m = 16, ef_construction = 512);"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_bgc_emb_hnsw;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX idx_prot_emb_hnsw ON discovery_protein_embedding "
                "USING hnsw (vector halfvec_cosine_ops) WITH (m = 16, ef_construction = 512);"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_prot_emb_hnsw;",
        ),
    ]
