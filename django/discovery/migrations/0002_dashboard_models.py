import django.db.models.deletion
import pgvector.django
import pgvector.django.indexes
import pgvector.django.vector
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0001_initial"),
        ("mgnify_bgcs", "0020_bgc_is_mibig"),
    ]

    operations = [
        # ── Ensure pgvector supports halfvec (>= 0.7.0) and install ltree ─────
        migrations.RunSQL(
            sql="ALTER EXTENSION vector UPDATE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS ltree;",
            reverse_sql="DROP EXTENSION IF EXISTS ltree;",
        ),
        # ── Drop old models FIRST (some share table names with new models) ────
        # Remove FK fields before deleting models
        migrations.RemoveField(model_name="gcf", name="representative_bgc"),
        migrations.RemoveField(model_name="gcfmembership", name="gcf"),
        migrations.RemoveField(model_name="gcfmembership", name="bgc"),
        migrations.RemoveField(model_name="genomescore", name="assembly"),
        migrations.RemoveField(model_name="mibigreference", name="bgc"),
        migrations.RemoveField(model_name="naturalproduct", name="bgc"),
        migrations.DeleteModel(name="BgcScore"),
        migrations.DeleteModel(name="GCF"),
        migrations.DeleteModel(name="GCFMembership"),
        migrations.DeleteModel(name="GenomeScore"),
        migrations.DeleteModel(name="MibigReference"),
        migrations.DeleteModel(name="NaturalProduct"),
        # ── New standalone models (no FKs to other new models) ─────────────────
        migrations.CreateModel(
            name="PrecomputedStats",
            fields=[
                (
                    "key",
                    models.CharField(max_length=100, primary_key=True, serialize=False),
                ),
                ("data", models.JSONField(default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "discovery_precomputed_stats",
            },
        ),
        migrations.CreateModel(
            name="DashboardBgcClass",
            fields=[
                (
                    "id",
                    models.AutoField(primary_key=True, serialize=False),
                ),
                (
                    "name",
                    models.CharField(db_index=True, max_length=255, unique=True),
                ),
                ("bgc_count", models.IntegerField(default=0)),
            ],
            options={
                "db_table": "discovery_bgc_class",
            },
        ),
        migrations.CreateModel(
            name="DashboardDomain",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "acc",
                    models.CharField(db_index=True, max_length=50, unique=True),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "ref_db",
                    models.CharField(blank=True, default="", max_length=50),
                ),
                ("description", models.TextField(blank=True, default="")),
                ("bgc_count", models.IntegerField(default=0)),
            ],
            options={
                "db_table": "discovery_domain",
                "indexes": [
                    models.Index(
                        fields=["-bgc_count"], name="idx_dd_count_desc"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DashboardGenome",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "assembly_accession",
                    models.CharField(db_index=True, max_length=255, unique=True),
                ),
                (
                    "organism_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "taxonomy_path",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="ltree dot-path, e.g. Bacteria.Actinobacteriota.Actinomycetia",
                        max_length=1024,
                    ),
                ),
                (
                    "taxonomy_kingdom",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "taxonomy_phylum",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "taxonomy_class",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "taxonomy_order",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "taxonomy_family",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "taxonomy_genus",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "taxonomy_species",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "biome_path",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="ltree dot-path, e.g. root.Environmental.Terrestrial.Soil",
                        max_length=512,
                    ),
                ),
                (
                    "is_type_strain",
                    models.BooleanField(db_index=True, default=False),
                ),
                (
                    "type_strain_catalog_url",
                    models.URLField(blank=True, default=""),
                ),
                ("genome_size_mb", models.FloatField(blank=True, null=True)),
                ("genome_quality", models.FloatField(blank=True, null=True)),
                (
                    "isolation_source",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("bgc_count", models.IntegerField(default=0)),
                ("l1_class_count", models.IntegerField(default=0)),
                ("bgc_diversity_score", models.FloatField(default=0.0)),
                ("bgc_novelty_score", models.FloatField(default=0.0)),
                ("bgc_density", models.FloatField(default=0.0)),
                ("taxonomic_novelty", models.FloatField(default=0.0)),
                (
                    "composite_score",
                    models.FloatField(db_index=True, default=0.0),
                ),
                ("pctl_diversity", models.FloatField(default=0.0)),
                ("pctl_novelty", models.FloatField(default=0.0)),
                ("pctl_density", models.FloatField(default=0.0)),
                (
                    "source_assembly_id",
                    models.IntegerField(db_index=True, unique=True),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "discovery_genome",
                "indexes": [
                    models.Index(
                        fields=["-composite_score"],
                        name="idx_dg_composite_desc",
                    ),
                    models.Index(
                        fields=["-bgc_novelty_score"],
                        name="idx_dg_novelty_desc",
                    ),
                    models.Index(
                        fields=["-bgc_diversity_score"],
                        name="idx_dg_diversity_desc",
                    ),
                    models.Index(
                        fields=["-bgc_density"],
                        name="idx_dg_density_desc",
                    ),
                    models.Index(
                        fields=["taxonomy_kingdom"],
                        name="idx_dg_tax_kingdom",
                    ),
                    models.Index(
                        fields=["taxonomy_phylum"],
                        name="idx_dg_tax_phylum",
                    ),
                    models.Index(
                        fields=["taxonomy_family"],
                        name="idx_dg_tax_family",
                    ),
                    models.Index(
                        fields=["taxonomy_genus"],
                        name="idx_dg_tax_genus",
                    ),
                    models.Index(
                        fields=["organism_name"],
                        name="idx_dg_organism",
                    ),
                    models.Index(
                        fields=["biome_path"],
                        name="idx_dg_biome",
                    ),
                ],
            },
        ),
        # ── DashboardBgc ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name="DashboardBgc",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("bgc_accession", models.CharField(db_index=True, max_length=50)),
                (
                    "contig_accession",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("start_position", models.IntegerField()),
                ("end_position", models.IntegerField()),
                (
                    "classification_path",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="ltree dot-path, e.g. Polyketide.Macrolide.14_membered",
                        max_length=512,
                    ),
                ),
                (
                    "classification_l1",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=100
                    ),
                ),
                (
                    "classification_l2",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "classification_l3",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                ("novelty_score", models.FloatField(default=0.0)),
                ("domain_novelty", models.FloatField(default=0.0)),
                ("size_kb", models.FloatField(default=0.0)),
                (
                    "nearest_mibig_accession",
                    models.CharField(blank=True, default="", max_length=50),
                ),
                (
                    "nearest_mibig_distance",
                    models.FloatField(blank=True, null=True),
                ),
                ("is_partial", models.BooleanField(default=False)),
                ("is_validated", models.BooleanField(default=False)),
                ("is_mibig", models.BooleanField(default=False)),
                ("umap_x", models.FloatField(default=0.0)),
                ("umap_y", models.FloatField(default=0.0)),
                (
                    "gcf_id",
                    models.IntegerField(blank=True, db_index=True, null=True),
                ),
                (
                    "distance_to_gcf_representative",
                    models.FloatField(blank=True, null=True),
                ),
                (
                    "detector_names",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "source_bgc_id",
                    models.BigIntegerField(db_index=True, unique=True),
                ),
                ("source_contig_id", models.IntegerField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "genome",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bgcs",
                        to="discovery.dashboardgenome",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_bgc",
                "indexes": [
                    models.Index(
                        fields=["-novelty_score"],
                        name="idx_db_novelty_desc",
                    ),
                    models.Index(
                        fields=["-domain_novelty"],
                        name="idx_db_domain_nov_desc",
                    ),
                    models.Index(
                        fields=["-size_kb"],
                        name="idx_db_size_desc",
                    ),
                    models.Index(
                        fields=["genome", "-novelty_score"],
                        name="idx_db_genome_novelty",
                    ),
                    models.Index(
                        fields=["umap_x", "umap_y"],
                        name="idx_db_umap",
                    ),
                ],
            },
        ),
        # ── Models that depend on DashboardBgc ────────────────────────────────
        migrations.CreateModel(
            name="BgcEmbedding",
            fields=[
                (
                    "bgc",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="embedding",
                        serialize=False,
                        to="discovery.dashboardbgc",
                    ),
                ),
                ("vector", pgvector.django.HalfVectorField(dimensions=1152)),
            ],
            options={
                "db_table": "discovery_bgc_embedding",
                "indexes": [
                    pgvector.django.indexes.HnswIndex(
                        ef_construction=512,
                        fields=["vector"],
                        m=16,
                        name="idx_bgc_emb_hnsw",
                        opclasses=["halfvec_cosine_ops"],
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DashboardCds",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "bgc",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cds_list",
                        to="discovery.dashboardbgc",
                    ),
                ),
                (
                    "protein_id_str",
                    models.CharField(
                        help_text="Display identifier (mgyp or protein_identifier)",
                        max_length=255,
                    ),
                ),
                ("start_position", models.IntegerField()),
                ("end_position", models.IntegerField()),
                ("strand", models.SmallIntegerField()),
                ("protein_length", models.IntegerField(default=0)),
                (
                    "gene_caller",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "cluster_representative",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "sequence",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Amino acid sequence",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_cds",
                "indexes": [
                    models.Index(
                        fields=["bgc", "start_position"],
                        name="idx_dcds_bgc_start",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BgcDomain",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "bgc",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bgc_domains",
                        to="discovery.dashboardbgc",
                    ),
                ),
                (
                    "cds",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="domains",
                        to="discovery.dashboardcds",
                    ),
                ),
                (
                    "domain_acc",
                    models.CharField(db_index=True, max_length=50),
                ),
                ("domain_name", models.CharField(max_length=255)),
                ("domain_description", models.TextField(blank=True, default="")),
                (
                    "ref_db",
                    models.CharField(blank=True, default="", max_length=50),
                ),
                ("start_position", models.IntegerField(default=0)),
                ("end_position", models.IntegerField(default=0)),
                ("score", models.FloatField(blank=True, null=True)),
            ],
            options={
                "db_table": "discovery_bgc_domain",
                "indexes": [
                    models.Index(
                        fields=["domain_acc", "bgc"],
                        name="idx_bgcdom_acc_bgc",
                    ),
                    models.Index(
                        fields=["bgc", "domain_acc"],
                        name="idx_bgcdom_bgc_acc",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=["bgc", "domain_acc", "cds", "start_position", "end_position"],
                        name="uniq_bgc_domain_pos",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DashboardGCF",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "family_id",
                    models.CharField(db_index=True, max_length=255, unique=True),
                ),
                (
                    "representative_bgc",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="represented_gcf",
                        to="discovery.dashboardbgc",
                    ),
                ),
                ("member_count", models.IntegerField(default=0)),
                (
                    "known_chemistry_annotation",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "mibig_accession",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("mean_novelty", models.FloatField(default=0.0)),
                ("mibig_count", models.IntegerField(default=0)),
            ],
            options={
                "db_table": "discovery_gcf",
                "verbose_name": "GCF",
                "verbose_name_plural": "GCFs",
            },
        ),
        migrations.CreateModel(
            name="DashboardMibigReference",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "accession",
                    models.CharField(db_index=True, max_length=50, unique=True),
                ),
                ("compound_name", models.CharField(max_length=255)),
                ("bgc_class", models.CharField(max_length=100)),
                ("umap_x", models.FloatField()),
                ("umap_y", models.FloatField()),
                (
                    "embedding",
                    pgvector.django.vector.VectorField(
                        blank=True, dimensions=1152, null=True
                    ),
                ),
                (
                    "dashboard_bgc",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mibig_ref",
                        to="discovery.dashboardbgc",
                    ),
                ),
            ],
            options={
                "db_table": "discovery_mibig_reference",
                "indexes": [
                    pgvector.django.indexes.HnswIndex(
                        ef_construction=512,
                        fields=["embedding"],
                        m=16,
                        name="idx_mibig_emb_hnsw",
                        opclasses=["vector_cosine_ops"],
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DashboardNaturalProduct",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "bgc",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="natural_products",
                        to="discovery.dashboardbgc",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("smiles", models.TextField(blank=True, default="")),
                (
                    "np_class_path",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="ltree dot-path, e.g. Polyketide.Macrolide.Erythromycin",
                        max_length=512,
                    ),
                ),
                (
                    "chemical_class_l1",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "chemical_class_l2",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "chemical_class_l3",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                ("structure_svg_base64", models.TextField(blank=True, default="")),
                (
                    "producing_organism",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("morgan_fp", models.BinaryField(blank=True, null=True)),
            ],
            options={
                "db_table": "discovery_natural_product",
                "indexes": [
                    models.Index(
                        fields=["chemical_class_l1"],
                        name="idx_dnp_class_l1",
                    ),
                    models.Index(
                        fields=["bgc"],
                        name="idx_dnp_bgc",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ProteinEmbedding",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "source_protein_id",
                    models.IntegerField(db_index=True, unique=True),
                ),
                ("protein_sha256", models.CharField(db_index=True, max_length=64)),
                ("vector", pgvector.django.HalfVectorField(dimensions=1152)),
            ],
            options={
                "db_table": "discovery_protein_embedding",
                "indexes": [
                    pgvector.django.indexes.HnswIndex(
                        ef_construction=512,
                        fields=["vector"],
                        m=16,
                        name="idx_prot_emb_hnsw",
                        opclasses=["halfvec_cosine_ops"],
                    ),
                ],
            },
        ),
    ]
