"""Squashed initial migration for the iBGC-first discovery schema.

Replaces the entire pre-refactor migration chain (0001..0027). Old
``mgnify_bgcs`` cross-app FK dependencies are gone with the legacy app.

Operator rebuild flow (dev only):
    1. pg_dump for rollback.
    2. DROP every old discovery_* and mgnify_bgcs_* table (or DROP SCHEMA public CASCADE on a dev DB).
    3. DELETE FROM django_migrations WHERE app IN ('discovery', 'mgnify_bgcs');
    4. python manage.py migrate
    5. python manage.py load_discovery_data --data-dir <dir> --truncate
    6. python manage.py build_integrated_bgcs
    7. (HPC) clustering → manage.py import_clustering_results
"""

import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        # ── PostgreSQL extensions ───────────────────────────────────────────
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS ltree;",
            reverse_sql="DROP EXTENSION IF EXISTS ltree;",
        ),
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS btree_gist;",
            reverse_sql="DROP EXTENSION IF EXISTS btree_gist;",
        ),

        # ── Accession-minting sequence (consumed by services.accession_registry) ─
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS discovery_cbgc_accession_seq AS bigint;",
            reverse_sql="DROP SEQUENCE IF EXISTS discovery_cbgc_accession_seq;",
        ),

        # ── Lookups & catalog tables (no FKs) ───────────────────────────────
        migrations.CreateModel(
            name="AssemblySource",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100, unique=True)),
            ],
            options={"db_table": "discovery_assembly_source"},
        ),
        migrations.CreateModel(
            name="DashboardDetector",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(db_index=True, max_length=255, unique=True)),
                ("tool", models.CharField(max_length=255)),
                ("version", models.CharField(max_length=50)),
                ("tool_name_code", models.CharField(max_length=3)),
                ("version_sort_key", models.PositiveIntegerField(default=0)),
            ],
            options={
                "db_table": "discovery_detector",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tool", "version"),
                        name="uniq_detector_tool_version",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ClusteringRun",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("domain_sources", models.JSONField(default=list)),
                (
                    "domain_vocab",
                    models.CharField(
                        choices=[
                            ("RAW", "Raw signature accessions"),
                            ("IPR_PROJECTED", "IPR entry when available, else signature"),
                        ],
                        default="IPR_PROJECTED",
                        max_length=20,
                    ),
                ),
                ("score_weights", models.JSONField(default=list)),
                ("knn_k", models.PositiveSmallIntegerField()),
                ("leiden_resolutions", models.JSONField(default=list)),
                ("seed", models.PositiveIntegerField(default=42)),
                ("n_proteins", models.PositiveIntegerField(default=0)),
                ("n_ibgcs", models.PositiveIntegerField(default=0)),
                ("n_levels", models.PositiveSmallIntegerField(default=0)),
                ("n_root_communities", models.PositiveIntegerField(default=0)),
                ("n_leaf_communities", models.PositiveIntegerField(default=0)),
                ("igraph_version", models.CharField(blank=True, default="", max_length=50)),
                ("leidenalg_version", models.CharField(blank=True, default="", max_length=50)),
                ("umap_version", models.CharField(blank=True, default="", max_length=50)),
                ("scipy_version", models.CharField(blank=True, default="", max_length=50)),
                ("sha256", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "discovery_clustering_run",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="DashboardBgcClass",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(db_index=True, max_length=255, unique=True)),
                ("bgc_count", models.IntegerField(default=0)),
            ],
            options={"db_table": "discovery_bgc_class"},
        ),
        migrations.CreateModel(
            name="DashboardDomain",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("acc", models.CharField(db_index=True, max_length=50, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("ref_db", models.CharField(blank=True, default="", max_length=50)),
                ("description", models.TextField(blank=True, default="")),
                ("bgc_count", models.IntegerField(default=0)),
            ],
            options={
                "db_table": "discovery_domain",
                "indexes": [
                    models.Index(fields=["-bgc_count"], name="idx_dd_count_desc"),
                ],
            },
        ),
        migrations.CreateModel(
            name="PrecomputedStats",
            fields=[
                ("key", models.CharField(max_length=100, primary_key=True, serialize=False)),
                ("data", models.JSONField(default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "discovery_precomputed_stats"},
        ),
        migrations.CreateModel(
            name="DiscoveryStats",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("stats", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "discovery_stats",
                "ordering": ["-created_at"],
            },
        ),

        # ── Assembly + Contig ───────────────────────────────────────────────
        migrations.CreateModel(
            name="DashboardAssembly",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("assembly_accession", models.CharField(db_index=True, max_length=255, unique=True)),
                ("organism_name", models.CharField(blank=True, default="", max_length=255)),
                ("assembly_type", models.SmallIntegerField(choices=[(1, "metagenome"), (2, "genome"), (3, "region")], db_index=True, default=2)),
                ("biome_path", models.CharField(blank=True, default="", max_length=512)),
                ("is_type_strain", models.BooleanField(db_index=True, default=False)),
                ("type_strain_catalog_url", models.URLField(blank=True, default="")),
                ("assembly_size_mb", models.FloatField(blank=True, null=True)),
                ("url", models.URLField(blank=True, default="", max_length=512)),
                ("bgc_count", models.IntegerField(default=0)),
                ("l1_class_count", models.IntegerField(default=0)),
                ("bgc_diversity_score", models.FloatField(default=0.0)),
                ("bgc_novelty_score", models.FloatField(default=0.0)),
                ("bgc_density", models.FloatField(default=0.0)),
                ("taxonomic_novelty", models.FloatField(default=0.0)),
                ("pctl_diversity", models.FloatField(default=0.0)),
                ("pctl_novelty", models.FloatField(default=0.0)),
                ("pctl_density", models.FloatField(default=0.0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source",
                    models.ForeignKey(
                        blank=True,
                        db_index=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assemblies",
                        to="discovery.assemblysource",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_assembly",
                "indexes": [
                    models.Index(fields=["-bgc_novelty_score"], name="idx_da_novelty_desc"),
                    models.Index(fields=["-bgc_diversity_score"], name="idx_da_diversity_desc"),
                    models.Index(fields=["-bgc_density"], name="idx_da_density_desc"),
                    models.Index(fields=["organism_name"], name="idx_da_organism"),
                    models.Index(fields=["biome_path"], name="idx_da_biome"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DashboardContig",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("sequence_sha256", models.CharField(db_index=True, max_length=64, unique=True)),
                ("accession", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("length", models.IntegerField(default=0)),
                ("taxonomy_path", models.CharField(blank=True, default="", max_length=1024)),
                (
                    "assembly",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contigs",
                        to="discovery.dashboardassembly",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_contig",
                "indexes": [
                    models.Index(fields=["taxonomy_path"], name="idx_dcontig_tax_path"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ContigSequence",
            fields=[
                (
                    "contig",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="seq",
                        serialize=False,
                        to="discovery.dashboardcontig",
                    ),
                ),
                ("data", models.BinaryField()),
            ],
            options={"db_table": "discovery_contig_sequence"},
        ),

        # ── ConsensusBgc (cBGC) ─────────────────────────────────────────────
        migrations.CreateModel(
            name="ConsensusBgc",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("accession", models.CharField(db_index=True, max_length=20, unique=True)),
                ("bgc_range", django.contrib.postgres.fields.ranges.IntegerRangeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "contig",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cbgcs",
                        to="discovery.dashboardcontig",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_cbgc",
                "constraints": [
                    django.contrib.postgres.constraints.ExclusionConstraint(
                        name="excl_cbgc_overlap",
                        expressions=[("contig", "="), ("bgc_range", "&&")],
                    ),
                ],
            },
        ),

        # ── IntegratedBgc (iBGC) ────────────────────────────────────────────
        migrations.CreateModel(
            name="IntegratedBgc",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("accession", models.CharField(db_index=True, max_length=20, unique=True)),
                ("bgc_range", django.contrib.postgres.fields.ranges.IntegerRangeField()),
                ("source_tools", models.JSONField(default=list)),
                ("gene_cluster_family", models.CharField(blank=True, db_index=True, default="", max_length=512)),
                ("umap_x", models.FloatField(blank=True, null=True)),
                ("umap_y", models.FloatField(blank=True, null=True)),
                ("umap_projected", models.BooleanField(default=False)),
                ("novelty_score", models.FloatField(blank=True, null=True)),
                ("domain_novelty", models.FloatField(blank=True, null=True)),
                ("classified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "cbgc",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ibgcs",
                        to="discovery.consensusbgc",
                    ),
                ),
                (
                    "contig",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ibgcs",
                        to="discovery.dashboardcontig",
                    ),
                ),
                (
                    "classification_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ibgcs",
                        to="discovery.clusteringrun",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_ibgc",
                "constraints": [
                    django.contrib.postgres.constraints.ExclusionConstraint(
                        name="excl_ibgc_overlap_in_cbgc",
                        expressions=[("cbgc", "="), ("bgc_range", "&&")],
                    ),
                ],
                "indexes": [
                    models.Index(fields=["gene_cluster_family"], name="idx_ibgc_gcf"),
                ],
            },
        ),

        # ── Accession Registry & Alias ──────────────────────────────────────
        migrations.CreateModel(
            name="AccessionRegistry",
            fields=[
                (
                    "accession",
                    models.CharField(max_length=20, primary_key=True, serialize=False),
                ),
                (
                    "entity_type",
                    models.CharField(
                        choices=[("cbgc", "Consensus BGC"), ("ibgc", "Integrated BGC")],
                        db_index=True,
                        max_length=10,
                    ),
                ),
                ("contig_accession", models.CharField(db_index=True, max_length=255)),
                ("start_pos", models.IntegerField()),
                ("end_pos", models.IntegerField()),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                (
                    "current_cbgc",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="registry_entries",
                        to="discovery.consensusbgc",
                    ),
                ),
                (
                    "current_ibgc",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="registry_entries",
                        to="discovery.integratedbgc",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_accession_registry",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("entity_type", "contig_accession", "start_pos", "end_pos"),
                        name="uniq_registry_identity",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["entity_type", "contig_accession", "start_pos", "end_pos"],
                        name="idx_registry_identity",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AccessionAlias",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("alias_accession", models.CharField(db_index=True, max_length=50, unique=True)),
                (
                    "registry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="aliases",
                        to="discovery.accessionregistry",
                    ),
                ),
            ],
            options={"db_table": "discovery_accession_alias"},
        ),

        # ── SourceBgcPrediction ─────────────────────────────────────────────
        migrations.CreateModel(
            name="SourceBgcPrediction",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("prediction_accession", models.CharField(db_index=True, max_length=50)),
                ("bgc_range", django.contrib.postgres.fields.ranges.IntegerRangeField()),
                ("is_partial", models.BooleanField(default=False)),
                ("is_validated", models.BooleanField(default=False)),
                ("bgc_number", models.PositiveSmallIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assembly",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="source_bgcs",
                        to="discovery.dashboardassembly",
                    ),
                ),
                (
                    "contig",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="source_bgcs",
                        to="discovery.dashboardcontig",
                    ),
                ),
                (
                    "detector",
                    models.ForeignKey(
                        blank=True,
                        db_index=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="source_bgcs",
                        to="discovery.dashboarddetector",
                    ),
                ),
                (
                    "cbgc",
                    models.ForeignKey(
                        blank=True,
                        db_index=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="source_bgcs",
                        to="discovery.consensusbgc",
                    ),
                ),
                (
                    "integrated_bgc",
                    models.ForeignKey(
                        blank=True,
                        db_index=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="source_predictions",
                        to="discovery.integratedbgc",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_source_bgc",
                "constraints": [
                    django.contrib.postgres.constraints.ExclusionConstraint(
                        name="excl_source_bgc_overlap_per_detector",
                        expressions=[("contig", "="), ("detector", "="), ("bgc_range", "&&")],
                    ),
                ],
                "indexes": [
                    models.Index(fields=["assembly"], name="idx_sbgc_assembly"),
                    models.Index(fields=["integrated_bgc"], name="idx_sbgc_ibgc"),
                ],
            },
        ),

        # ── Contig CDS & Sequence & Domain & ChemOnt ────────────────────────
        migrations.CreateModel(
            name="ContigCds",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("cds_range", django.contrib.postgres.fields.ranges.IntegerRangeField()),
                ("strand", models.SmallIntegerField()),
                ("protein_id_str", models.CharField(max_length=255)),
                ("protein_length", models.IntegerField(default=0)),
                ("gene_caller", models.CharField(blank=True, default="", max_length=100)),
                ("cluster_representative", models.CharField(blank=True, default="", max_length=64)),
                ("protein_sha256", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                (
                    "contig",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cds_list",
                        to="discovery.dashboardcontig",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_cds",
                "constraints": [
                    django.contrib.postgres.constraints.ExclusionConstraint(
                        name="uniq_cds_contig_range_strand",
                        expressions=[("contig", "="), ("cds_range", "="), ("strand", "=")],
                    ),
                ],
                "indexes": [
                    models.Index(fields=["protein_sha256"], name="idx_dcds_prot_sha256"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CdsSequence",
            fields=[
                (
                    "cds",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="seq",
                        serialize=False,
                        to="discovery.contigcds",
                    ),
                ),
                ("data", models.BinaryField()),
            ],
            options={"db_table": "discovery_cds_sequence"},
        ),
        migrations.CreateModel(
            name="ContigDomain",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("domain_acc", models.CharField(db_index=True, max_length=50)),
                ("domain_name", models.CharField(max_length=255)),
                ("domain_description", models.TextField(blank=True, default="")),
                ("ref_db", models.CharField(blank=True, default="", max_length=50)),
                ("go_slim", models.JSONField(blank=True, default=list)),
                ("interpro_entry_acc", models.CharField(blank=True, default="", max_length=20)),
                ("interpro_entry_description", models.CharField(blank=True, default="", max_length=255)),
                ("go_terms", models.JSONField(blank=True, default=list)),
                ("start_position", models.IntegerField(default=0)),
                ("end_position", models.IntegerField(default=0)),
                ("score", models.FloatField(blank=True, null=True)),
                ("url", models.URLField(blank=True, default="", max_length=512)),
                (
                    "cds",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="domains",
                        to="discovery.contigcds",
                    ),
                ),
                (
                    "contig",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="domains",
                        to="discovery.dashboardcontig",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_domain_hit",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("cds", "domain_acc", "start_position", "end_position"),
                        name="uniq_domain_cds_acc_pos",
                    ),
                ],
                "indexes": [
                    models.Index(fields=["domain_acc", "contig"], name="idx_dom_acc_contig"),
                    models.Index(fields=["contig", "domain_acc"], name="idx_dom_contig_acc"),
                    models.Index(fields=["contig", "ref_db", "domain_acc"], name="idx_dom_contig_ref_acc"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CdsChemOnt",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("chemont_id", models.CharField(max_length=30)),
                ("chemont_name", models.CharField(max_length=255)),
                ("probability", models.FloatField(default=0.0)),
                ("weight", models.FloatField(default=0.0)),
                (
                    "cds",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chemont",
                        to="discovery.contigcds",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_cds_chemont",
                "unique_together": {("cds", "chemont_id")},
                "indexes": [
                    models.Index(fields=["chemont_id"], name="idx_cdschemont_cid"),
                    models.Index(fields=["cds"], name="idx_cdschemont_cds"),
                ],
            },
        ),

        # ── GCF & clustering snapshot ───────────────────────────────────────
        migrations.CreateModel(
            name="DashboardGCF",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("family_path", models.CharField(db_index=True, max_length=512)),
                ("parent_path", models.CharField(blank=True, db_index=True, default="", max_length=512)),
                ("level", models.PositiveSmallIntegerField()),
                ("member_count", models.IntegerField(default=0)),
                ("validated_count", models.IntegerField(default=0)),
                ("mean_novelty", models.FloatField(default=0.0)),
                ("descendant_count", models.IntegerField(default=0)),
                (
                    "clustering_run",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gcfs",
                        to="discovery.clusteringrun",
                    ),
                ),
                (
                    "representative_ibgc",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="represented_gcfs",
                        to="discovery.integratedbgc",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_gcf",
                "verbose_name": "GCF",
                "verbose_name_plural": "GCFs",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("clustering_run", "family_path"),
                        name="uniq_gcf_run_path",
                    ),
                ],
                "indexes": [
                    models.Index(fields=["clustering_run", "level"], name="idx_gcf_run_level"),
                    models.Index(fields=["clustering_run", "parent_path"], name="idx_gcf_run_parent"),
                ],
            },
        ),
        migrations.CreateModel(
            name="IbgcClusteringSnapshot",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("umap_x", models.FloatField(blank=True, null=True)),
                ("umap_y", models.FloatField(blank=True, null=True)),
                ("umap_projected", models.BooleanField(default=False)),
                ("gene_cluster_family", models.CharField(blank=True, default="", max_length=512)),
                ("novelty_score", models.FloatField(blank=True, null=True)),
                ("domain_novelty", models.FloatField(blank=True, null=True)),
                (
                    "clustering_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ibgc_snapshots",
                        to="discovery.clusteringrun",
                    ),
                ),
                (
                    "ibgc",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="clustering_snapshots",
                        to="discovery.integratedbgc",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_ibgc_clustering_snapshot",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("clustering_run", "ibgc"),
                        name="uniq_snapshot_run_ibgc",
                    ),
                ],
                "indexes": [
                    models.Index(fields=["clustering_run"], name="idx_snapshot_run"),
                ],
            },
        ),

        # ── iBGC Natural Product ────────────────────────────────────────────
        migrations.CreateModel(
            name="IbgcNaturalProduct",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("smiles", models.TextField(blank=True, default="")),
                ("dedup_hash", models.CharField(max_length=64)),
                ("np_class_path", models.CharField(blank=True, default="", max_length=512)),
                ("structure_svg_base64", models.TextField(blank=True, default="")),
                ("morgan_fp", models.BinaryField(blank=True, null=True)),
                (
                    "ibgc",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="natural_products",
                        to="discovery.integratedbgc",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_ibgc_natural_product",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ibgc", "dedup_hash"),
                        name="uniq_np_ibgc_dedup",
                    ),
                ],
                "indexes": [
                    models.Index(fields=["np_class_path"], name="idx_dnp_class_path"),
                    models.Index(fields=["ibgc"], name="idx_dnp_ibgc"),
                ],
            },
        ),

        # ── ltree GiST functional indexes ───────────────────────────────────
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_dcontig_tax_ltree ON discovery_contig USING gist ((taxonomy_path::ltree));",
            reverse_sql="DROP INDEX IF EXISTS idx_dcontig_tax_ltree;",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_da_biome_ltree ON discovery_assembly USING gist ((biome_path::ltree));",
            reverse_sql="DROP INDEX IF EXISTS idx_da_biome_ltree;",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_ibgc_gcf_ltree ON discovery_ibgc USING gist ((gene_cluster_family::ltree));",
            reverse_sql="DROP INDEX IF EXISTS idx_ibgc_gcf_ltree;",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_gcf_path_ltree ON discovery_gcf USING gist ((family_path::ltree));",
            reverse_sql="DROP INDEX IF EXISTS idx_gcf_path_ltree;",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_gcf_parent_path_ltree ON discovery_gcf USING gist ((parent_path::ltree));",
            reverse_sql="DROP INDEX IF EXISTS idx_gcf_parent_path_ltree;",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_dnp_class_path_ltree ON discovery_ibgc_natural_product USING gist ((np_class_path::ltree));",
            reverse_sql="DROP INDEX IF EXISTS idx_dnp_class_path_ltree;",
        ),
    ]
