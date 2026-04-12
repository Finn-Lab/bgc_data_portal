"""Make source_protein_id nullable and add unique constraint on protein_sha256.

source_protein_id is nullable so that rows ingested from embeddings_protein.tsv
(which only supply protein_sha256 + vector) do not require a back-reference to
the mgnify_bgcs app's Protein table.

protein_sha256 becomes the uniqueness key for the ingestion pipeline, enabling
idempotent re-runs via ignore_conflicts=True.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0011_naturalproductchemontclass"),
    ]

    operations = [
        migrations.AlterField(
            model_name="proteinembedding",
            name="source_protein_id",
            field=models.IntegerField(
                blank=True,
                db_index=True,
                null=True,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="proteinembedding",
            name="protein_sha256",
            field=models.CharField(max_length=64, unique=True),
        ),
    ]
