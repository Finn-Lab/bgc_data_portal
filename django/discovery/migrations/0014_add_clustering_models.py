from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0013_reduce_embedding_dim_to_960"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClusteringRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("n_samples", models.PositiveIntegerField()),
                ("pca_components", models.PositiveSmallIntegerField()),
                ("umap_n_neighbors", models.PositiveSmallIntegerField()),
                ("umap_min_dist", models.FloatField()),
                ("umap_n_components", models.PositiveSmallIntegerField()),
                ("umap_metric", models.CharField(max_length=50)),
                ("hdbscan_min_cluster_size", models.PositiveSmallIntegerField()),
                ("hdbscan_min_samples", models.PositiveSmallIntegerField()),
                ("knn_k", models.PositiveSmallIntegerField()),
                ("sklearn_version", models.CharField(max_length=50)),
                ("umap_version", models.CharField(max_length=50)),
                ("hdbscan_version", models.CharField(max_length=50)),
                ("n_bgcs_sampled", models.PositiveIntegerField(default=0)),
                ("n_clusters_found", models.PositiveIntegerField(default=0)),
                ("n_noise_points", models.PositiveIntegerField(default=0)),
                ("n_bgcs_classified", models.PositiveIntegerField(default=0)),
                ("pca_blob", models.BinaryField()),
                ("umap_blob", models.BinaryField()),
                ("hdbscan_blob", models.BinaryField()),
                ("knn_blob", models.BinaryField()),
                ("umap2d_blob", models.BinaryField()),
                ("sha256", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "discovery_clustering_run",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="BgcCluster",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cluster_id", models.IntegerField(help_text="Raw HDBSCAN label (-1 = noise)")),
                ("label", models.CharField(help_text="ltree-safe label, e.g. 'cluster.0042' or 'cluster.noise'", max_length=255)),
                ("n_bgcs", models.PositiveIntegerField(default=0)),
                ("n_validated", models.PositiveIntegerField(default=0)),
                (
                    "clustering_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="clusters",
                        to="discovery.clusteringrun",
                    ),
                ),
                (
                    "representative_bgc",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="representative_of_clusters",
                        to="discovery.dashboardbgc",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_bgc_cluster",
            },
        ),
        migrations.CreateModel(
            name="ClusterAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_noise", models.BooleanField(default=False)),
                ("assigned_by_knn", models.BooleanField(default=False, help_text="True if assigned via KNN (not in training sample)")),
                (
                    "bgc",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cluster_assignments",
                        to="discovery.dashboardbgc",
                    ),
                ),
                (
                    "cluster",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="discovery.bgccluster",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="discovery.clusteringrun",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_cluster_assignment",
            },
        ),
        migrations.AddIndex(
            model_name="bgccluster",
            index=models.Index(fields=["clustering_run", "cluster_id"], name="idx_bgccluster_run_id"),
        ),
        migrations.AlterUniqueTogether(
            name="bgccluster",
            unique_together={("clustering_run", "cluster_id")},
        ),
        migrations.AddIndex(
            model_name="clusterassignment",
            index=models.Index(fields=["run", "bgc"], name="idx_ca_run_bgc"),
        ),
        migrations.AddIndex(
            model_name="clusterassignment",
            index=models.Index(fields=["run", "cluster"], name="idx_ca_run_cluster"),
        ),
        migrations.AlterUniqueTogether(
            name="clusterassignment",
            unique_together={("run", "bgc")},
        ),
    ]
