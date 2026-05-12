"""Domain + adjacency clustering schema.

Replaces the protein-vector clustering pipeline:
  * Adds NonRedundantBGC (consolidated BGC region used as the clustering input
    unit; built from latest-version GECCO+SanntiS merges + standalone antiSMASH
    calls).
  * Adds DashboardBgc.non_redundant_bgc FK and the ``merged`` classification
    source option.
  * Adds a composite (bgc, ref_db, domain_acc) index on BgcDomain to speed the
    source-filtered domain-matrix scan.
  * Reshapes ClusteringRun parameters: removes protein-pair fields, adds
    domain_sources + score_weights JSON fields, renames n_bgcs → n_nrbs.
  * Drops the now-unused ProteinSimilarPair table.

Rollback note: ProteinSimilarPair is dropped. To restore, re-run the legacy
pair-building pipeline (which itself is deleted in this change); a full
re-implementation would be required.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0017_pair_based_clustering"),
    ]

    operations = [
        # ── 1. Create NonRedundantBGC ─────────────────────────────────
        migrations.CreateModel(
            name="NonRedundantBGC",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("start_position", models.IntegerField()),
                ("end_position", models.IntegerField()),
                (
                    "source_tools",
                    models.JSONField(
                        default=list,
                        help_text="Sorted, deduped tool names that contributed, e.g. ['GECCO','SanntiS']",
                    ),
                ),
                (
                    "gene_cluster_family",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="ltree dot-path, e.g. cluster.0042.0007.0003 (leaf of the hierarchy)",
                        max_length=512,
                    ),
                ),
                ("umap_x", models.FloatField(blank=True, null=True)),
                ("umap_y", models.FloatField(blank=True, null=True)),
                ("classified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "contig",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="non_redundant_bgcs",
                        to="discovery.dashboardcontig",
                    ),
                ),
                (
                    "classification_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="non_redundant_bgcs",
                        to="discovery.clusteringrun",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_non_redundant_bgc",
            },
        ),
        migrations.AddConstraint(
            model_name="nonredundantbgc",
            constraint=models.UniqueConstraint(
                fields=("contig", "start_position", "end_position"),
                name="uniq_nrb_contig_pos",
            ),
        ),
        migrations.AddIndex(
            model_name="nonredundantbgc",
            index=models.Index(
                fields=["contig", "start_position", "end_position"],
                name="idx_nrb_contig_pos",
            ),
        ),
        migrations.AddIndex(
            model_name="nonredundantbgc",
            index=models.Index(
                fields=["gene_cluster_family"],
                name="idx_nrb_gcf",
            ),
        ),

        # ── 2. DashboardBgc additions ─────────────────────────────────
        migrations.AddField(
            model_name="dashboardbgc",
            name="non_redundant_bgc",
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="source_bgcs",
                to="discovery.nonredundantbgc",
            ),
        ),
        migrations.AlterField(
            model_name="dashboardbgc",
            name="classification_source",
            field=models.CharField(
                choices=[
                    ("primary", "primary"),
                    ("merged", "merged"),
                    ("knn", "knn"),
                    ("unclassified", "unclassified"),
                ],
                db_index=True,
                default="unclassified",
                max_length=16,
            ),
        ),

        # ── 3. BgcDomain index for source-filtered scans ──────────────
        migrations.AddIndex(
            model_name="bgcdomain",
            index=models.Index(
                fields=["bgc", "ref_db", "domain_acc"],
                name="idx_bgcdom_bgc_ref_acc",
            ),
        ),

        # ── 4. ClusteringRun field reshape ────────────────────────────
        migrations.RemoveField(model_name="clusteringrun", name="pair_floor"),
        migrations.RemoveField(model_name="clusteringrun", name="dice_threshold"),
        migrations.RemoveField(model_name="clusteringrun", name="n_pairs"),
        migrations.RemoveField(model_name="clusteringrun", name="metric_name"),
        migrations.AddField(
            model_name="clusteringrun",
            name="domain_sources",
            field=models.JSONField(
                default=list,
                help_text="Domain ref_db sources used (upper-case), e.g. ['PFAM','NCBIFAM']",
            ),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="score_weights",
            field=models.JSONField(
                default=list,
                help_text="(w_domain, w_adjacency) used for the composite Dice score, e.g. [0.5, 0.5]",
            ),
        ),
        migrations.RenameField(
            model_name="clusteringrun",
            old_name="n_bgcs",
            new_name="n_nrbs",
        ),
        migrations.AlterField(
            model_name="clusteringrun",
            name="leiden_resolutions",
            field=models.JSONField(
                default=list,
                help_text="CPM resolution_parameter values (one per nesting level, coarsest first)",
            ),
        ),
        migrations.AlterField(
            model_name="clusteringrun",
            name="knn_k",
            field=models.PositiveSmallIntegerField(),
        ),

        # ── 5. Drop ProteinSimilarPair ────────────────────────────────
        migrations.DeleteModel(name="ProteinSimilarPair"),
    ]
