"""Per-NRB classification snapshot for rollback after HPC clustering imports.

``import_clustering_results`` writes one row per primary / partial NRB before
overwriting the live columns on ``NonRedundantBGC`` so
``set_active_clustering_run`` can restore a prior run's state without
recomputing anything.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0022_nonredundantbgc_scoring_columns"),
    ]

    operations = [
        migrations.CreateModel(
            name="NonRedundantBGCClusteringSnapshot",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("umap_x", models.FloatField(blank=True, null=True)),
                ("umap_y", models.FloatField(blank=True, null=True)),
                ("umap_projected", models.BooleanField(default=False)),
                (
                    "gene_cluster_family",
                    models.CharField(blank=True, default="", max_length=512),
                ),
                ("novelty_score", models.FloatField(blank=True, null=True)),
                ("domain_novelty", models.FloatField(blank=True, null=True)),
                (
                    "clustering_run",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="nrb_snapshots",
                        to="discovery.clusteringrun",
                    ),
                ),
                (
                    "nrb",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="clustering_snapshots",
                        to="discovery.nonredundantbgc",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_nrb_clustering_snapshot",
            },
        ),
        migrations.AddConstraint(
            model_name="nonredundantbgcclusteringsnapshot",
            constraint=models.UniqueConstraint(
                fields=["clustering_run", "nrb"], name="uniq_snapshot_run_nrb",
            ),
        ),
        migrations.AddIndex(
            model_name="nonredundantbgcclusteringsnapshot",
            index=models.Index(fields=["clustering_run"], name="idx_snapshot_run"),
        ),
    ]
