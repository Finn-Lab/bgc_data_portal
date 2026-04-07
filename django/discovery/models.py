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
from pgvector.django import HalfVectorField, HnswIndex


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
    sequence_sha256 = models.CharField(max_length=64, unique=True, db_index=True)
    accession = models.CharField(max_length=255, blank=True, default="", db_index=True)
    length = models.IntegerField(default=0)

    # Taxonomy — ltree dot-path for this contig
    taxonomy_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. Bacteria.Actinomycetota.Actinomycetia...",
    )

    # Cross-reference to mgnify_bgcs.Contig (integer, NOT a Django FK)
    source_contig_id = models.IntegerField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "discovery_contig"
        indexes = [
            models.Index(fields=["taxonomy_path"], name="idx_dcontig_tax_path"),
        ]

    def __str__(self):
        return self.accession or self.sequence_sha256


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


# ── Detector ──────────────────────────────────────────────────────────────────


class DashboardDetector(models.Model):
    """BGC detection tool + version lookup.

    ``tool_name_code`` is a stable 3-letter uppercase code derived from ``tool``
    (e.g. "ANT" for antiSMASH).  ``version_sort_key`` is a monotonically
    increasing integer so that ``ORDER BY version_sort_key DESC`` yields the
    latest version without parsing version strings in SQL.
    """

    id = models.AutoField(primary_key=True)
    name = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text='Human-readable label, e.g. "antiSMASH v7.1"',
    )
    tool = models.CharField(max_length=255, help_text='Tool name, e.g. "antiSMASH"')
    version = models.CharField(max_length=50, help_text='Semver string, e.g. "7.1.0"')
    tool_name_code = models.CharField(
        max_length=3,
        help_text='3-letter uppercase code, e.g. "ANT"',
    )
    version_sort_key = models.PositiveIntegerField(
        default=0,
        help_text="Monotonic integer for DB-level version ordering",
    )

    class Meta:
        db_table = "discovery_detector"
        constraints = [
            models.UniqueConstraint(
                fields=["tool", "version"],
                name="uniq_detector_tool_version",
            ),
        ]

    def __str__(self):
        return self.name


# ── Aggregated Region ─────────────────────────────────────────────────────────


class DashboardRegion(models.Model):
    """Aggregated genomic region on a contig where one or more BGC predictions
    overlap.  The region accession (``MGYB{id:08}``) is the first component of
    the structured BGC accession.
    """

    id = models.BigAutoField(primary_key=True)
    contig = models.ForeignKey(
        DashboardContig,
        on_delete=models.CASCADE,
        related_name="regions",
        db_index=True,
    )
    start_position = models.IntegerField()
    end_position = models.IntegerField()

    @property
    def accession(self):
        return f"MGYB{self.id:08}"

    class Meta:
        db_table = "discovery_region"
        constraints = [
            models.UniqueConstraint(
                fields=["contig", "start_position", "end_position"],
                name="uniq_region_contig_pos",
            ),
        ]
        indexes = [
            models.Index(
                fields=["contig", "start_position", "end_position"],
                name="idx_region_contig_pos",
            ),
        ]

    def __str__(self):
        return self.accession


class RegionAccessionAlias(models.Model):
    """Maps old region accessions to the surviving region after a merge."""

    id = models.AutoField(primary_key=True)
    alias_accession = models.CharField(max_length=50, unique=True, db_index=True)
    region = models.ForeignKey(
        DashboardRegion,
        on_delete=models.CASCADE,
        related_name="aliases",
    )

    class Meta:
        db_table = "discovery_region_accession_alias"

    def __str__(self):
        return f"{self.alias_accession} → {self.region.accession}"


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

    # Parent contig
    contig = models.ForeignKey(
        DashboardContig,
        on_delete=models.CASCADE,
        related_name="bgcs",
        db_index=True,
    )

    # Identity
    bgc_accession = models.CharField(max_length=50, db_index=True)
    start_position = models.IntegerField()
    end_position = models.IntegerField()

    # Classification — ltree path
    classification_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. Polyketide.Macrolide.14_membered",
    )

    # Scores
    novelty_score = models.FloatField(default=0.0)
    domain_novelty = models.FloatField(default=0.0)
    size_kb = models.FloatField(default=0.0)
    nearest_validated_accession = models.CharField(max_length=50, blank=True, default="")
    nearest_validated_distance = models.FloatField(null=True, blank=True)

    # Flags
    is_partial = models.BooleanField(default=False)
    is_validated = models.BooleanField(default=False)

    # UMAP coordinates (proper columns, not JSON)
    umap_x = models.FloatField(default=0.0)
    umap_y = models.FloatField(default=0.0)

    # Gene Cluster Family — ltree dot-path
    gene_cluster_family = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. GCF_001.SubFamily_A",
    )

    # Detector info
    detector = models.ForeignKey(
        DashboardDetector,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bgcs",
        db_index=True,
    )

    # Region / accession
    region = models.ForeignKey(
        DashboardRegion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bgcs",
        db_index=True,
    )
    bgc_number = models.PositiveSmallIntegerField(
        default=0,
        help_text="2-digit incremental within region + detector",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_bgc"
        constraints = [
            models.UniqueConstraint(
                fields=["contig", "start_position", "end_position", "detector"],
                name="uniq_bgc_contig_pos_detector",
            ),
        ]
        indexes = [
            models.Index(fields=["-novelty_score"], name="idx_db_novelty_desc"),
            models.Index(fields=["-domain_novelty"], name="idx_db_domain_nov_desc"),
            models.Index(fields=["-size_kb"], name="idx_db_size_desc"),
            models.Index(fields=["assembly", "-novelty_score"], name="idx_db_assembly_novelty"),
            models.Index(fields=["umap_x", "umap_y"], name="idx_db_umap"),
            models.Index(fields=["gene_cluster_family"], name="idx_db_gcf_path"),
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
    """Gene Cluster Family — materialized from DashboardBgc.gene_cluster_family ltree."""

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
    validated_accession = models.CharField(max_length=255, blank=True, default="")
    mean_novelty = models.FloatField(default=0.0)
    validated_count = models.IntegerField(default=0)

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

    # NP chemical class hierarchy — ltree path
    np_class_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. Polyketide.Macrolide.Erythromycin",
    )

    structure_svg_base64 = models.TextField(blank=True, default="")

    # Precomputed Morgan fingerprint (2048-bit) for Tanimoto similarity search
    morgan_fp = models.BinaryField(null=True, blank=True)

    class Meta:
        db_table = "discovery_natural_product"
        indexes = [
            models.Index(fields=["np_class_path"], name="idx_dnp_class_path"),
            models.Index(fields=["bgc"], name="idx_dnp_bgc"),
        ]

    def __str__(self):
        return self.name


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
