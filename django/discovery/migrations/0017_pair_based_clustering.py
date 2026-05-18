"""Pair-based hierarchical Leiden clustering schema.

Drops the old PCA → UMAP-20d → HDBSCAN → KNN clustering tables
(BgcCluster, ClusterAssignment) and the model-blob fields on ClusteringRun.
Rewrites DashboardGCF as a hierarchical (ltree) node table keyed on
(clustering_run, family_path). Adds ProteinSimilarPair as the durable source
for protein-protein cosine matches at a permissive floor (e.g. 0.7), and
adds classification provenance fields on DashboardBgc.

Rollback note: the BgcCluster / ClusterAssignment tables are dropped — to
recover historic cluster assignments, re-run the new clustering pipeline.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0016_bgcdomain_go_slim"),
    ]

    operations = [
        # ── 1. Drop old per-cluster tables ────────────────────────────
        migrations.DeleteModel(name="ClusterAssignment"),
        migrations.DeleteModel(name="BgcCluster"),

        # ── 2. Rewrite ClusteringRun ──────────────────────────────────
        migrations.RemoveField(model_name="clusteringrun", name="n_samples"),
        migrations.RemoveField(model_name="clusteringrun", name="pca_components"),
        migrations.RemoveField(model_name="clusteringrun", name="umap_n_neighbors"),
        migrations.RemoveField(model_name="clusteringrun", name="umap_min_dist"),
        migrations.RemoveField(model_name="clusteringrun", name="umap_n_components"),
        migrations.RemoveField(model_name="clusteringrun", name="umap_metric"),
        migrations.RemoveField(model_name="clusteringrun", name="hdbscan_min_cluster_size"),
        migrations.RemoveField(model_name="clusteringrun", name="hdbscan_min_samples"),
        migrations.RemoveField(model_name="clusteringrun", name="sklearn_version"),
        migrations.RemoveField(model_name="clusteringrun", name="hdbscan_version"),
        migrations.RemoveField(model_name="clusteringrun", name="n_bgcs_sampled"),
        migrations.RemoveField(model_name="clusteringrun", name="n_clusters_found"),
        migrations.RemoveField(model_name="clusteringrun", name="n_noise_points"),
        migrations.RemoveField(model_name="clusteringrun", name="n_bgcs_classified"),
        migrations.RemoveField(model_name="clusteringrun", name="pca_blob"),
        migrations.RemoveField(model_name="clusteringrun", name="umap_blob"),
        migrations.RemoveField(model_name="clusteringrun", name="hdbscan_blob"),
        migrations.RemoveField(model_name="clusteringrun", name="knn_blob"),
        migrations.RemoveField(model_name="clusteringrun", name="umap2d_blob"),

        migrations.AddField(
            model_name="clusteringrun",
            name="pair_floor",
            field=models.FloatField(default=0.7),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="dice_threshold",
            field=models.FloatField(default=0.9),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="leiden_resolutions",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="metric_name",
            field=models.CharField(default="dice", max_length=50),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="seed",
            field=models.PositiveIntegerField(default=42),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="n_proteins",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="n_pairs",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="n_bgcs",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="n_levels",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="n_root_communities",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="n_leaf_communities",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="igraph_version",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="leidenalg_version",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="scipy_version",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AlterField(
            model_name="clusteringrun",
            name="umap_version",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AlterField(
            model_name="clusteringrun",
            name="knn_k",
            field=models.PositiveSmallIntegerField(default=5),
        ),

        # ── 3. Rewrite DashboardGCF as a hierarchy node table ─────────
        migrations.RemoveField(model_name="dashboardgcf", name="family_id"),
        migrations.RemoveField(model_name="dashboardgcf", name="known_chemistry_annotation"),
        migrations.RemoveField(model_name="dashboardgcf", name="validated_accession"),
        # Legacy GCF rows reference the pre-0017 PCA/UMAP/HDBSCAN pipeline
        # and have no valid clustering_run target; drop them so the new
        # non-nullable FK can be added cleanly. run_bgc_clustering --apply
        # repopulates the table after migrate.
        migrations.RunSQL(
            sql="DELETE FROM discovery_gcf;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddField(
            model_name="dashboardgcf",
            name="clustering_run",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="gcfs",
                to="discovery.clusteringrun",
            ),
        ),
        migrations.AddField(
            model_name="dashboardgcf",
            name="family_path",
            field=models.CharField(default="", max_length=512),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="dashboardgcf",
            name="parent_path",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AddField(
            model_name="dashboardgcf",
            name="level",
            field=models.PositiveSmallIntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="dashboardgcf",
            name="descendant_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="dashboardgcf",
            name="representative_bgc",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="represented_gcfs",
                to="discovery.dashboardbgc",
            ),
        ),
        migrations.AddIndex(
            model_name="dashboardgcf",
            index=models.Index(fields=["family_path"], name="idx_gcf_path"),
        ),
        migrations.AddIndex(
            model_name="dashboardgcf",
            index=models.Index(fields=["parent_path"], name="idx_gcf_parent"),
        ),
        migrations.AddIndex(
            model_name="dashboardgcf",
            index=models.Index(fields=["clustering_run", "level"], name="idx_gcf_run_level"),
        ),
        migrations.AddIndex(
            model_name="dashboardgcf",
            index=models.Index(fields=["clustering_run", "parent_path"], name="idx_gcf_run_parent"),
        ),
        migrations.AddConstraint(
            model_name="dashboardgcf",
            constraint=models.UniqueConstraint(
                fields=("clustering_run", "family_path"),
                name="uniq_gcf_run_path",
            ),
        ),

        # ── 4. New table: ProteinSimilarPair ──────────────────────────
        migrations.CreateModel(
            name="ProteinSimilarPair",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("protein_a_sha256", models.CharField(db_index=True, max_length=64)),
                ("protein_b_sha256", models.CharField(max_length=64)),
                ("cosine", models.FloatField(help_text="Cosine similarity (>= floor)")),
            ],
            options={
                "db_table": "discovery_protein_similar_pair",
            },
        ),
        migrations.AddConstraint(
            model_name="proteinsimilarpair",
            constraint=models.UniqueConstraint(
                fields=("protein_a_sha256", "protein_b_sha256"),
                name="uniq_protein_pair_a_b",
            ),
        ),
        migrations.AddIndex(
            model_name="proteinsimilarpair",
            index=models.Index(fields=["protein_a_sha256", "cosine"], name="idx_psp_a_cos"),
        ),
        migrations.AddIndex(
            model_name="proteinsimilarpair",
            index=models.Index(fields=["protein_b_sha256"], name="idx_psp_b"),
        ),

        # ── 5. DashboardBgc: classification provenance ─────────────────
        migrations.AddField(
            model_name="dashboardbgc",
            name="classification_source",
            field=models.CharField(
                choices=[
                    ("primary", "primary"),
                    ("knn", "knn"),
                    ("unclassified", "unclassified"),
                ],
                db_index=True,
                default="unclassified",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="dashboardbgc",
            name="classified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dashboardbgc",
            name="classification_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="classified_bgcs",
                to="discovery.clusteringrun",
            ),
        ),

        # ── 6. ltree GiST index for prefix / ancestor queries ─────────
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_gcf_path_ltree ON discovery_gcf USING gist ((family_path::ltree));",
            reverse_sql="DROP INDEX IF EXISTS idx_gcf_path_ltree;",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_gcf_parent_path_ltree ON discovery_gcf USING gist ((parent_path::ltree));",
            reverse_sql="DROP INDEX IF EXISTS idx_gcf_parent_path_ltree;",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_db_gcf_path_ltree ON discovery_bgc USING gist ((gene_cluster_family::ltree));",
            reverse_sql="DROP INDEX IF EXISTS idx_db_gcf_path_ltree;",
        ),
    ]
