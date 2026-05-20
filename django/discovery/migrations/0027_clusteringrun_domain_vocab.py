"""Add ``ClusteringRun.domain_vocab`` to record the matrix label space.

New rows default to ``IPR_PROJECTED`` (the post-cutover behaviour: signature
accessions are projected to their ``interpro_entry_acc`` when set). Existing
runs are migrated to ``RAW`` so historical results stay interpretable — they
were produced before the projection rolled out and their scoring caches use
the raw signature vocabulary.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0026_rename_nonredundantbgc_to_integratedbgc"),
    ]

    operations = [
        migrations.AddField(
            model_name="clusteringrun",
            name="domain_vocab",
            field=models.CharField(
                choices=[
                    ("RAW", "Raw signature accessions"),
                    ("IPR_PROJECTED", "IPR entry when available, else signature"),
                ],
                default="IPR_PROJECTED",
                help_text=(
                    "Label space used for M_domains columns and M_pairs vocab. "
                    "'IPR_PROJECTED' = InterPro entry acc when set on a signature, "
                    "else the raw signature acc. 'RAW' = legacy pre-projection runs."
                ),
                max_length=20,
            ),
        ),
        # Stamp existing rows as RAW — they predate the projection.
        migrations.RunSQL(
            sql="UPDATE discovery_clustering_run SET domain_vocab = 'RAW';",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
