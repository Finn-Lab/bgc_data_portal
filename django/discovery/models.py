"""Discovery Platform models — self-contained, optimized for dashboard reads at scale.

All dashboard data lives here — fully self-contained with zero imports from
mgnify_bgcs.  Data is bulk-loaded via the ``load_discovery_data`` management
command.

Hierarchical fields (taxonomy_path, biome_path, classification_path, np_class_path)
store dot-delimited ltree paths.  The migration installs the PostgreSQL ``ltree``
extension and creates functional GiST indexes so these columns support native
hierarchical queries (``<@``, ``@>``, ``subpath``, ``nlevel``) when cast to ``ltree``.
"""

import zlib

from django.db import models
from pgvector.django import HalfVectorField, HnswIndex, VectorField


# ── Assembly source lookup ─────────────────────────────────────────────────────


class AssemblySource(models.Model):
    """Lookup table for assembly data sources (auto-populated via get_or_create)."""

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "discovery_assembly_source"

    def __str__(self):
        return self.name


# ── Assembly type choices ─────────────────────────────────────────────────────


class AssemblyType(models.IntegerChoices):
    METAGENOME = 1, "metagenome"
    GENOME = 2, "genome"
    REGION = 3, "region"


# ── Assembly ───────────────────────────────────────────────────────────────────


class DashboardAssembly(models.Model):
    """Denormalized assembly row: Assembly metadata + score in one table."""

    id = models.BigAutoField(primary_key=True)

    # Identity
    assembly_accession = models.CharField(max_length=255, unique=True, db_index=True)
    organism_name = models.CharField(max_length=255, blank=True, default="")

    # Source database/collection
    source = models.ForeignKey(
        AssemblySource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assemblies",
        db_index=True,
    )

    # Assembly type
    assembly_type = models.SmallIntegerField(
        choices=AssemblyType.choices,
        default=AssemblyType.GENOME,
        db_index=True,
    )

    # Dominant taxonomy — precomputed from contigs at load time
    dominant_taxonomy_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Most common taxonomy_path among contigs, or empty if mixed",
    )
    dominant_taxonomy_label = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Species name or 'Mixed (N taxa)'",
    )

    # Biome — ltree dot-path
    biome_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. root.Environmental.Terrestrial.Soil",
    )

    # Assembly metadata
    is_type_strain = models.BooleanField(default=False, db_index=True)
    type_strain_catalog_url = models.URLField(blank=True, default="")
    assembly_size_mb = models.FloatField(null=True, blank=True)
    assembly_quality = models.FloatField(null=True, blank=True)
    isolation_source = models.CharField(max_length=255, blank=True, default="")
    url = models.URLField(max_length=512, blank=True, default="")

    # Scores (denormalized from GenomeScore)
    bgc_count = models.IntegerField(default=0)
    l1_class_count = models.IntegerField(default=0)
    bgc_diversity_score = models.FloatField(default=0.0)
    bgc_novelty_score = models.FloatField(default=0.0)
    bgc_density = models.FloatField(default=0.0)
    taxonomic_novelty = models.FloatField(default=0.0)

    # Precomputed percentile ranks (0–100)
    pctl_diversity = models.FloatField(default=0.0)
    pctl_novelty = models.FloatField(default=0.0)
    pctl_density = models.FloatField(default=0.0)

    # Cross-reference to mgnify_bgcs.Assembly (integer, NOT a Django FK)
    source_assembly_id = models.IntegerField(unique=True, db_index=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_assembly"
        indexes = [
            # Roster sort columns
            models.Index(fields=["-bgc_novelty_score"], name="idx_da_novelty_desc"),
            models.Index(fields=["-bgc_diversity_score"], name="idx_da_diversity_desc"),
            models.Index(fields=["-bgc_density"], name="idx_da_density_desc"),
            # Text search
            models.Index(fields=["organism_name"], name="idx_da_organism"),
            # Biome prefix queries (btree; ltree GiST index added via RunSQL)
            models.Index(fields=["biome_path"], name="idx_da_biome"),
            # Dominant taxonomy prefix queries
            models.Index(fields=["dominant_taxonomy_path"], name="idx_da_dom_tax"),
        ]

    def __str__(self):
        return self.assembly_accession


# ── Contig ──────────────────────────────────────────────────────────────────────


class DashboardContig(models.Model):
    """Contig within an assembly — multiple BGCs may share the same contig."""

    id = models.BigAutoField(primary_key=True)
    assembly = models.ForeignKey(
        DashboardAssembly,
        on_delete=models.CASCADE,
        related_name="contigs",
        db_index=True,
    )
    accession = models.CharField(max_length=255, db_index=True)
    length = models.IntegerField(default=0)

    # Taxonomy — ltree dot-path for this contig
    taxonomy_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. Bacteria.Actinomycetota.Actinomycetia...",
    )

    # Cross-reference to mgnify_bgcs.Contig (integer, NOT a Django FK)
    source_contig_id = models.IntegerField(unique=True, db_index=True)

    class Meta:
        db_table = "discovery_contig"
        indexes = [
            models.Index(fields=["taxonomy_path"], name="idx_dcontig_tax_path"),
        ]

    def __str__(self):
        return self.accession


class ContigSequence(models.Model):
    """On-demand nucleotide sequence for a contig — zlib-compressed."""

    contig = models.OneToOneField(
        DashboardContig,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="seq",
    )
    data = models.BinaryField(help_text="zlib-compressed nucleotide sequence")

    class Meta:
        db_table = "discovery_contig_sequence"

    def get_sequence(self) -> str:
        if self.data:
            return zlib.decompress(bytes(self.data)).decode("utf-8")
        return ""

    @staticmethod
    def compress_sequence(seq: str) -> bytes:
        return zlib.compress(seq.encode("utf-8"))

    def __str__(self):
        return f"Sequence for {self.contig_id}"


# ── BGC ─────────────────────────────────────────────────────────────────────────


class DashboardBgc(models.Model):
    """Denormalized BGC row: Bgc + BgcScore + Contig chain in one table."""

    id = models.BigAutoField(primary_key=True)

    # Parent assembly (FK within discovery schema)
    assembly = models.ForeignKey(
        DashboardAssembly,
        on_delete=models.CASCADE,
        related_name="bgcs",
        db_index=True,
    )

    # Parent contig (nullable — populated by data loading)
    contig = models.ForeignKey(
        DashboardContig,
        on_delete=models.CASCADE,
        related_name="bgcs",
        null=True,
        blank=True,
        db_index=True,
    )

    # Identity
    bgc_accession = models.CharField(max_length=50, db_index=True)
    contig_accession = models.CharField(max_length=255, blank=True, default="")
    start_position = models.IntegerField()
    end_position = models.IntegerField()

    # Classification — ltree path + individual levels
    classification_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. Polyketide.Macrolide.14_membered",
    )
    classification_l1 = models.CharField(max_length=100, blank=True, default="", db_index=True)
    classification_l2 = models.CharField(max_length=100, blank=True, default="")
    classification_l3 = models.CharField(max_length=100, blank=True, default="")

    # Scores
    novelty_score = models.FloatField(default=0.0)
    domain_novelty = models.FloatField(default=0.0)
    size_kb = models.FloatField(default=0.0)
    nearest_mibig_accession = models.CharField(max_length=50, blank=True, default="")
    nearest_mibig_distance = models.FloatField(null=True, blank=True)

    # Flags
    is_partial = models.BooleanField(default=False)
    is_validated = models.BooleanField(default=False)
    is_mibig = models.BooleanField(default=False)

    # UMAP coordinates (proper columns, not JSON)
    umap_x = models.FloatField(default=0.0)
    umap_y = models.FloatField(default=0.0)

    # GCF placement (integer FK-by-value to DashboardGCF.id)
    gcf_id = models.IntegerField(null=True, blank=True, db_index=True)
    distance_to_gcf_representative = models.FloatField(null=True, blank=True)

    # Detector info (comma-separated names)
    detector_names = models.CharField(max_length=255, blank=True, default="")

    # Cross-references to mgnify_bgcs (integers, NOT Django FKs)
    source_bgc_id = models.BigIntegerField(unique=True, db_index=True)
    source_contig_id = models.IntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_bgc"
        indexes = [
            models.Index(fields=["-novelty_score"], name="idx_db_novelty_desc"),
            models.Index(fields=["-domain_novelty"], name="idx_db_domain_nov_desc"),
            models.Index(fields=["-size_kb"], name="idx_db_size_desc"),
            models.Index(fields=["assembly", "-novelty_score"], name="idx_db_assembly_novelty"),
            models.Index(fields=["umap_x", "umap_y"], name="idx_db_umap"),
        ]

    def __str__(self):
        return self.bgc_accession


# ── Embeddings (separate tables, half precision) ───────────────────────────────


class BgcEmbedding(models.Model):
    """BGC embedding vector in a dedicated table (halfvec for storage efficiency)."""

    bgc = models.OneToOneField(
        DashboardBgc,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="embedding",
    )
    vector = HalfVectorField(dimensions=1152)

    class Meta:
        db_table = "discovery_bgc_embedding"
        indexes = [
            HnswIndex(
                fields=["vector"],
                name="idx_bgc_emb_hnsw",
                opclasses=["halfvec_cosine_ops"],
                m=16,
                ef_construction=512,
            ),
        ]

    def __str__(self):
        return f"Embedding for {self.bgc_id}"


class ProteinEmbedding(models.Model):
    """Protein embedding vector in a dedicated table (halfvec)."""

    id = models.BigAutoField(primary_key=True)
    source_protein_id = models.IntegerField(unique=True, db_index=True)
    protein_sha256 = models.CharField(max_length=64, db_index=True)
    vector = HalfVectorField(dimensions=1152)

    class Meta:
        db_table = "discovery_protein_embedding"
        indexes = [
            HnswIndex(
                fields=["vector"],
                name="idx_prot_emb_hnsw",
                opclasses=["halfvec_cosine_ops"],
                m=16,
                ef_construction=512,
            ),
        ]

    def __str__(self):
        return f"Embedding for protein {self.source_protein_id}"


# ── BGC–Domain association (denormalized) ───────────────────────────────────────


class DashboardCds(models.Model):
    """Coding sequence within a BGC region — self-contained for region views."""

    id = models.BigAutoField(primary_key=True)
    bgc = models.ForeignKey(
        DashboardBgc,
        on_delete=models.CASCADE,
        related_name="cds_list",
    )
    protein_id_str = models.CharField(
        max_length=255,
        help_text="Display identifier (mgyp or protein_identifier)",
    )
    start_position = models.IntegerField()
    end_position = models.IntegerField()
    strand = models.SmallIntegerField()
    protein_length = models.IntegerField(default=0)
    gene_caller = models.CharField(max_length=100, blank=True, default="")
    cluster_representative = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "discovery_cds"
        indexes = [
            models.Index(fields=["bgc", "start_position"], name="idx_dcds_bgc_start"),
        ]

    def __str__(self):
        return f"CDS {self.protein_id_str} in BGC {self.bgc_id}"


class CdsSequence(models.Model):
    """On-demand amino acid sequence for a CDS — zlib-compressed."""

    cds = models.OneToOneField(
        DashboardCds,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="seq",
    )
    data = models.BinaryField(help_text="zlib-compressed amino acid sequence")

    class Meta:
        db_table = "discovery_cds_sequence"

    def get_sequence(self) -> str:
        if self.data:
            return zlib.decompress(bytes(self.data)).decode("utf-8")
        return ""

    @staticmethod
    def compress_sequence(seq: str) -> bytes:
        return zlib.compress(seq.encode("utf-8"))

    def __str__(self):
        return f"Sequence for CDS {self.cds_id}"


class BgcDomain(models.Model):
    """Denormalized BGC↔domain association.

    Eliminates the 5-join chain Domain→ProteinDomain→Protein→CDS→Contig→BGC.
    Stores one row per domain hit (including positional data on the protein)
    so the region view and domain architecture can be served self-contained.
    """

    id = models.BigAutoField(primary_key=True)
    bgc = models.ForeignKey(
        DashboardBgc,
        on_delete=models.CASCADE,
        related_name="bgc_domains",
    )
    cds = models.ForeignKey(
        DashboardCds,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="domains",
    )
    domain_acc = models.CharField(max_length=50, db_index=True)
    domain_name = models.CharField(max_length=255)
    domain_description = models.TextField(blank=True, default="")
    ref_db = models.CharField(max_length=50, blank=True, default="")
    # Positional data on the protein (amino acid coordinates)
    start_position = models.IntegerField(default=0)
    end_position = models.IntegerField(default=0)
    score = models.FloatField(null=True, blank=True)
    url = models.URLField(max_length=512, blank=True, default="")

    class Meta:
        db_table = "discovery_bgc_domain"
        indexes = [
            models.Index(fields=["domain_acc", "bgc"], name="idx_bgcdom_acc_bgc"),
            models.Index(fields=["bgc", "domain_acc"], name="idx_bgcdom_bgc_acc"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["bgc", "domain_acc", "cds", "start_position", "end_position"],
                name="uniq_bgc_domain_pos",
            ),
        ]

    def __str__(self):
        return f"{self.domain_acc} in BGC {self.bgc_id}"


# ── Gene Cluster Family ─────────────────────────────────────────────────────────


class DashboardGCF(models.Model):
    """Gene Cluster Family — self-contained copy for the dashboard."""

    id = models.AutoField(primary_key=True)
    family_id = models.CharField(max_length=255, unique=True, db_index=True)
    representative_bgc = models.ForeignKey(
        DashboardBgc,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="represented_gcf",
    )
    member_count = models.IntegerField(default=0)
    known_chemistry_annotation = models.CharField(max_length=255, blank=True, default="")
    mibig_accession = models.CharField(max_length=255, blank=True, default="")
    mean_novelty = models.FloatField(default=0.0)
    mibig_count = models.IntegerField(default=0)

    class Meta:
        db_table = "discovery_gcf"
        verbose_name = "GCF"
        verbose_name_plural = "GCFs"

    def __str__(self):
        return self.family_id


# ── Natural Product ──────────────────────────────────────────────────────────────


class DashboardNaturalProduct(models.Model):
    """Characterized natural product linked to a dashboard BGC."""

    id = models.BigAutoField(primary_key=True)
    bgc = models.ForeignKey(
        DashboardBgc,
        on_delete=models.CASCADE,
        related_name="natural_products",
    )
    name = models.CharField(max_length=255)
    smiles = models.TextField(blank=True, default="")

    # NP chemical class hierarchy — ltree path + individual levels
    np_class_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. Polyketide.Macrolide.Erythromycin",
    )
    chemical_class_l1 = models.CharField(max_length=100, blank=True, default="")
    chemical_class_l2 = models.CharField(max_length=100, blank=True, default="")
    chemical_class_l3 = models.CharField(max_length=100, blank=True, default="")

    structure_svg_base64 = models.TextField(blank=True, default="")
    producing_organism = models.CharField(max_length=255, blank=True, default="")

    # Precomputed Morgan fingerprint (2048-bit) for Tanimoto similarity search
    morgan_fp = models.BinaryField(null=True, blank=True)

    class Meta:
        db_table = "discovery_natural_product"
        indexes = [
            models.Index(fields=["chemical_class_l1"], name="idx_dnp_class_l1"),
            models.Index(fields=["bgc"], name="idx_dnp_bgc"),
        ]

    def __str__(self):
        return self.name


# ── MIBiG Reference ──────────────────────────────────────────────────────────────


class DashboardMibigReference(models.Model):
    """MIBiG reference cluster — known chemistry landmark in UMAP space."""

    id = models.AutoField(primary_key=True)
    accession = models.CharField(max_length=50, unique=True, db_index=True)
    compound_name = models.CharField(max_length=255)
    bgc_class = models.CharField(max_length=100)
    umap_x = models.FloatField()
    umap_y = models.FloatField()

    # Full-precision embedding (only ~200 rows, precision matters for reference lookups)
    embedding = VectorField(dimensions=1152, null=True, blank=True)

    dashboard_bgc = models.OneToOneField(
        DashboardBgc,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mibig_ref",
    )

    class Meta:
        db_table = "discovery_mibig_reference"
        indexes = [
            HnswIndex(
                fields=["embedding"],
                name="idx_mibig_emb_hnsw",
                opclasses=["vector_cosine_ops"],
                m=16,
                ef_construction=512,
            ),
        ]

    def __str__(self):
        return f"{self.accession} ({self.compound_name})"


# ── Catalog tables with precomputed counts ───────────────────────────────────────


class DashboardBgcClass(models.Model):
    """BGC classification label with precomputed count."""

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True, db_index=True)
    bgc_count = models.IntegerField(default=0)

    class Meta:
        db_table = "discovery_bgc_class"

    def __str__(self):
        return self.name


class DashboardDomain(models.Model):
    """Domain catalog entry with precomputed BGC count."""

    id = models.AutoField(primary_key=True)
    acc = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    ref_db = models.CharField(max_length=50, blank=True, default="")
    description = models.TextField(blank=True, default="")
    bgc_count = models.IntegerField(default=0)

    class Meta:
        db_table = "discovery_domain"
        indexes = [
            models.Index(fields=["-bgc_count"], name="idx_dd_count_desc"),
        ]

    def __str__(self):
        return f"{self.acc} ({self.name})"


# ── Precomputed statistics ───────────────────────────────────────────────────────


class PrecomputedStats(models.Model):
    """Precomputed aggregate statistics to avoid full-table scans.

    Keys:
        ``genome_global`` — score percentiles, type strain counts, averages,
                            radar reference values.
        ``bgc_global``    — novelty percentiles, complete/partial counts,
                            sparse threshold.
        ``taxonomy_sunburst`` — flat sunburst node list for unfiltered view.
        ``np_class_sunburst`` — NP chemical class sunburst.
        ``bgc_class_distribution`` — BGC class counts.
    """

    key = models.CharField(max_length=100, primary_key=True)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_precomputed_stats"

    def __str__(self):
        return self.key
