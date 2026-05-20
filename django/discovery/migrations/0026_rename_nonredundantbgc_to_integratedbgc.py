"""Rename ``NonRedundantBGC`` → ``IntegratedBGC`` (the iBGC rename).

User-facing terminology change: "Non-Redundant BGC" (NRB) becomes
"Integrated BGC" (iBGC). The rename covers:

  * Model classes ``NonRedundantBGC`` and ``NonRedundantBGCClusteringSnapshot``
  * Tables ``discovery_non_redundant_bgc`` → ``discovery_integrated_bgc`` and
    ``discovery_nrb_clustering_snapshot`` → ``discovery_ibgc_clustering_snapshot``
  * FK ``DashboardBgc.non_redundant_bgc`` → ``integrated_bgc``
  * FK ``IntegratedBGCClusteringSnapshot.nrb`` → ``ibgc``
  * Field ``ClusteringRun.n_nrbs`` → ``n_ibgcs``
  * Related names and constraint/index names embedding ``nrb``

``RenameModel`` + ``RenameField`` preserve data — no copy-and-drop. The
PostgreSQL constraint/index renames are done via ``RunSQL`` wrapped in
``SeparateDatabaseAndState`` so Django state matches DB names.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0025_bgcdomain_go_slim_list"),
    ]

    operations = [
        # ── Rename FK field on the snapshot first (before model rename) ──
        migrations.RenameField(
            model_name="nonredundantbgcclusteringsnapshot",
            old_name="nrb",
            new_name="ibgc",
        ),
        # ── Rename DashboardBgc FK to the to-be-renamed parent ──
        migrations.RenameField(
            model_name="dashboardbgc",
            old_name="non_redundant_bgc",
            new_name="integrated_bgc",
        ),
        # ── Rename ClusteringRun counter field ──
        migrations.RenameField(
            model_name="clusteringrun",
            old_name="n_nrbs",
            new_name="n_ibgcs",
        ),
        # ── Rename the models ──
        migrations.RenameModel(
            old_name="NonRedundantBGC",
            new_name="IntegratedBGC",
        ),
        migrations.RenameModel(
            old_name="NonRedundantBGCClusteringSnapshot",
            new_name="IntegratedBGCClusteringSnapshot",
        ),
        # ── Move tables to their new canonical names ──
        migrations.AlterModelTable(
            name="integratedbgc",
            table="discovery_integrated_bgc",
        ),
        migrations.AlterModelTable(
            name="integratedbgcclusteringsnapshot",
            table="discovery_ibgc_clustering_snapshot",
        ),
        # ── Rename constraints & indexes whose names embed "nrb" ──
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "discovery_integrated_bgc" '
                        'RENAME CONSTRAINT "uniq_nrb_contig_pos" TO "uniq_ibgc_contig_pos";'
                        'ALTER INDEX "idx_nrb_contig_pos" RENAME TO "idx_ibgc_contig_pos";'
                        'ALTER INDEX "idx_nrb_gcf" RENAME TO "idx_ibgc_gcf";'
                        'ALTER TABLE "discovery_ibgc_clustering_snapshot" '
                        'RENAME CONSTRAINT "uniq_snapshot_run_nrb" TO "uniq_snapshot_run_ibgc";'
                    ),
                    reverse_sql=(
                        'ALTER TABLE "discovery_integrated_bgc" '
                        'RENAME CONSTRAINT "uniq_ibgc_contig_pos" TO "uniq_nrb_contig_pos";'
                        'ALTER INDEX "idx_ibgc_contig_pos" RENAME TO "idx_nrb_contig_pos";'
                        'ALTER INDEX "idx_ibgc_gcf" RENAME TO "idx_nrb_gcf";'
                        'ALTER TABLE "discovery_ibgc_clustering_snapshot" '
                        'RENAME CONSTRAINT "uniq_snapshot_run_ibgc" TO "uniq_snapshot_run_nrb";'
                    ),
                ),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="integratedbgc",
                    name="uniq_nrb_contig_pos",
                ),
                migrations.AddConstraint(
                    model_name="integratedbgc",
                    constraint=models.UniqueConstraint(
                        fields=["contig", "start_position", "end_position"],
                        name="uniq_ibgc_contig_pos",
                    ),
                ),
                migrations.RemoveIndex(
                    model_name="integratedbgc",
                    name="idx_nrb_contig_pos",
                ),
                migrations.AddIndex(
                    model_name="integratedbgc",
                    index=models.Index(
                        fields=["contig", "start_position", "end_position"],
                        name="idx_ibgc_contig_pos",
                    ),
                ),
                migrations.RemoveIndex(
                    model_name="integratedbgc",
                    name="idx_nrb_gcf",
                ),
                migrations.AddIndex(
                    model_name="integratedbgc",
                    index=models.Index(
                        fields=["gene_cluster_family"],
                        name="idx_ibgc_gcf",
                    ),
                ),
                migrations.RemoveConstraint(
                    model_name="integratedbgcclusteringsnapshot",
                    name="uniq_snapshot_run_nrb",
                ),
                migrations.AddConstraint(
                    model_name="integratedbgcclusteringsnapshot",
                    constraint=models.UniqueConstraint(
                        fields=["clustering_run", "ibgc"],
                        name="uniq_snapshot_run_ibgc",
                    ),
                ),
            ],
        ),
    ]
