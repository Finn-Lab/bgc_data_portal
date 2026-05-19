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


# ── Non-Redundant BGC ─────────────────────────────────────────────────────────


class NonRedundantBGC(models.Model):
    """Consolidated BGC region. Complete registry of latest-version BGCs and
    input table for the clustering pipeline (which filters down to the
    clusterable subset).

    Built from latest-version ``DashboardBgc`` rows:
      * Validated BGCs (``is_validated=True``) become standalone NRBs
        regardless of tool or ``is_partial`` — ground truth, never merged
        with predictions, never tagged with overlapping antiSMASH, never
        absorbed.
      * Non-validated GECCO and SanntiS predictions on the same contig are
        merged via transitive interval overlap (any positive intersection
        joins a component), **regardless of ``is_partial``**. The merged
        interval spans ``min(starts) → max(ends)``.
      * For each chain NRB above, if any non-validated antiSMASH BGC on the
        same contig overlaps it, ``'antiSMASH'`` is added to that chain's
        ``source_tools``. AntiSMASH coordinates are never used to widen a
        chain interval.
      * Non-validated antiSMASH predictions (regardless of ``is_partial``)
        are admitted as their own NRB iff they do not overlap any
        already-built NRB on the same contig (validated standalones and
        chain NRBs alike). Overlapping antiSMASH calls are absorbed — their
        source ``DashboardBgc.non_redundant_bgc`` stays NULL and they are
        reclassified later via KNN.

    Source ``DashboardBgc`` rows point here via ``DashboardBgc.non_redundant_bgc``.
    Clustering writes ``gene_cluster_family`` and ``umap_x``/``umap_y`` here
    on the clusterable subset (NRBs with at least one ``is_partial=False``
    or ``is_validated=True`` source); source BGCs inherit those values via
    back-propagation. NRBs composed entirely of partial, non-validated
    sources are skipped by the clustering pipeline; their source BGCs
    receive paths via ``reclassify_bgcs``.
    """

    id = models.BigAutoField(primary_key=True)
    contig = models.ForeignKey(
        DashboardContig,
        on_delete=models.CASCADE,
        related_name="non_redundant_bgcs",
        db_index=True,
    )
    start_position = models.IntegerField()
    end_position = models.IntegerField()

    source_tools = models.JSONField(
        default=list,
        help_text="Sorted, deduped tool names that contributed, e.g. ['GECCO','SanntiS']",
    )

    gene_cluster_family = models.CharField(
        max_length=512,
        blank=True,
        default="",
        db_index=True,
        help_text="ltree dot-path, e.g. cluster.0042.0007.0003 (leaf of the hierarchy)",
    )
    umap_x = models.FloatField(null=True, blank=True)
    umap_y = models.FloatField(null=True, blank=True)
    umap_projected = models.BooleanField(
        default=False,
        help_text=(
            "True when umap_x/y were derived by averaging top-K nearest primary "
            "NRB coordinates (partials reclassified via KNN) rather than by the "
            "main UMAP layout. False for NRBs included in the clustering pass."
        ),
    )
    novelty_score = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "1 − max composite-Dice similarity to the nearest validated NRB. "
            "NULL when there are no validated NRBs in this run."
        ),
    )
    domain_novelty = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "Fraction of this NRB's domains not shared by any other NRB of the "
            "same leaf GCF. NULL for singleton GCFs and for NRBs without any "
            "domains of the selected sources."
        ),
    )
    classification_run = models.ForeignKey(
        "ClusteringRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="non_redundant_bgcs",
    )
    classified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_non_redundant_bgc"
        constraints = [
            models.UniqueConstraint(
                fields=["contig", "start_position", "end_position"],
                name="uniq_nrb_contig_pos",
            ),
        ]
        indexes = [
            models.Index(
                fields=["contig", "start_position", "end_position"],
                name="idx_nrb_contig_pos",
            ),
            models.Index(fields=["gene_cluster_family"], name="idx_nrb_gcf"),
        ]

    def __str__(self):
        return f"NRB#{self.pk} contig={self.contig_id} {self.start_position}-{self.end_position}"


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

    # Flags
    is_partial = models.BooleanField(default=False)
    is_validated = models.BooleanField(default=False)

    # UMAP coordinates (proper columns, not JSON)
    umap_x = models.FloatField(default=0.0)
    umap_y = models.FloatField(default=0.0)

    # Gene Cluster Family — leaf ltree dot-path, e.g. cluster.0042.0007.0003
    gene_cluster_family = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. cluster.0042.0007.0003 (leaf of the hierarchy)",
    )

    # ── Classification provenance (set by the clustering pipeline) ──────
    # ``primary``      — source BGC of a NonRedundantBGC that drove community detection
    # ``merged``       — source BGC of a NonRedundantBGC (set at NRB-build time, before clustering)
    # ``knn``          — assigned post-hoc via KNN reclassification (partials, stale BGCs)
    # ``unclassified`` — never matched any community (default for new rows)
    CLASSIFICATION_SOURCE_CHOICES = [
        ("primary", "primary"),
        ("merged", "merged"),
        ("knn", "knn"),
        ("unclassified", "unclassified"),
    ]
    classification_source = models.CharField(
        max_length=16,
        choices=CLASSIFICATION_SOURCE_CHOICES,
        default="unclassified",
        db_index=True,
    )
    classified_at = models.DateTimeField(null=True, blank=True)
    classification_run = models.ForeignKey(
        "ClusteringRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classified_bgcs",
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

    # Non-redundant BGC (set during NRB build; NULL for partials and absorbed antiSMASH calls)
    non_redundant_bgc = models.ForeignKey(
        NonRedundantBGC,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_bgcs",
        db_index=True,
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
    protein_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="SHA-256 hash of the amino acid sequence (used by the pyhmmer search index)",
    )

    class Meta:
        db_table = "discovery_cds"
        indexes = [
            models.Index(fields=["bgc", "start_position"], name="idx_dcds_bgc_start"),
            models.Index(fields=["protein_sha256"], name="idx_dcds_prot_sha256"),
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
    # Deduplicated, sorted list of GO-slim term names derived from go_terms
    # via discovery.services.go_slim.go_slim_for_terms. Populated inline at
    # ingestion / asset projection time.
    go_slim = models.JSONField(default=list, blank=True)
    # InterPro entry the signature maps to (populated when IPS runs with --iprlookup;
    # blank for signatures that do not map to an InterPro entry).
    interpro_entry_acc = models.CharField(max_length=20, blank=True, default="")
    interpro_entry_description = models.CharField(max_length=255, blank=True, default="")
    # GO term accessions associated with the signature (from IPS --goterms).
    # Stored as a list of strings, e.g. ["GO:0003824", "GO:0008152"].
    go_terms = models.JSONField(default=list, blank=True)
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
            models.Index(
                fields=["bgc", "ref_db", "domain_acc"],
                name="idx_bgcdom_bgc_ref_acc",
            ),
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


class ClusteringRun(models.Model):
    """One NRB-domain/adjacency-Dice → KNN-graph → hierarchical-CPM-Leiden run.

    Stores parameters and counts only. The hierarchy itself lives in DashboardGCF
    rows (one per node), on NonRedundantBGC.gene_cluster_family (leaf path per NRB),
    and on DashboardBgc.gene_cluster_family (back-propagated to source BGCs).
    Re-running with identical inputs yields the same ``sha256`` and therefore the
    same ``pk`` (idempotent via update_or_create).
    """

    created_at = models.DateTimeField(auto_now_add=True)

    # Pipeline parameters
    domain_sources = models.JSONField(
        default=list,
        help_text="Domain ref_db sources used (upper-case), e.g. ['PFAM','NCBIFAM']",
    )
    score_weights = models.JSONField(
        default=list,
        help_text="(w_domain, w_adjacency) used for the composite Dice score, e.g. [0.5, 0.5]",
    )
    knn_k = models.PositiveSmallIntegerField()
    leiden_resolutions = models.JSONField(
        default=list,
        help_text="CPM resolution_parameter values (one per nesting level, coarsest first)",
    )
    seed = models.PositiveIntegerField(default=42)

    # Counts
    n_proteins = models.PositiveIntegerField(default=0)
    n_nrbs = models.PositiveIntegerField(default=0)
    n_levels = models.PositiveSmallIntegerField(default=0)
    n_root_communities = models.PositiveIntegerField(default=0)
    n_leaf_communities = models.PositiveIntegerField(default=0)

    # Library versions used for this run
    igraph_version = models.CharField(max_length=50, blank=True, default="")
    leidenalg_version = models.CharField(max_length=50, blank=True, default="")
    umap_version = models.CharField(max_length=50, blank=True, default="")
    scipy_version = models.CharField(max_length=50, blank=True, default="")

    sha256 = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = "discovery_clustering_run"
        ordering = ["-created_at"]

    def __str__(self):
        return f"ClusteringRun {self.pk} ({self.created_at:%Y-%m-%d})"


# ── Gene Cluster Family ─────────────────────────────────────────────────────────


class DashboardGCF(models.Model):
    """A node in the hierarchical Leiden tree for a ClusteringRun.

    One row per node at every level: roots, internal, and leaves. The full
    ``family_path`` ltree string identifies the node uniquely; ``parent_path``
    points at the immediate parent (empty string for level-0 roots).
    """

    id = models.AutoField(primary_key=True)
    clustering_run = models.ForeignKey(
        ClusteringRun,
        on_delete=models.CASCADE,
        related_name="gcfs",
        db_index=True,
    )
    family_path = models.CharField(
        max_length=512,
        db_index=True,
        help_text="ltree dot-path identifying this node, e.g. cluster.0042.0007.0003",
    )
    parent_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        db_index=True,
        help_text="Immediate parent's family_path; empty string for level-0 roots",
    )
    level = models.PositiveSmallIntegerField(
        help_text="Depth in the hierarchy (0 = coarsest root level)",
    )
    representative_bgc = models.ForeignKey(
        DashboardBgc,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="represented_gcfs",
    )

    # Aggregates
    member_count = models.IntegerField(
        default=0,
        help_text="Total BGCs whose leaf path is a descendant of this node (or equal at leaves)",
    )
    validated_count = models.IntegerField(default=0)
    mean_novelty = models.FloatField(default=0.0)
    descendant_count = models.IntegerField(
        default=0,
        help_text="Number of immediate child nodes (0 for leaves)",
    )

    class Meta:
        db_table = "discovery_gcf"
        verbose_name = "GCF"
        verbose_name_plural = "GCFs"
        constraints = [
            models.UniqueConstraint(
                fields=["clustering_run", "family_path"],
                name="uniq_gcf_run_path",
            ),
        ]
        indexes = [
            models.Index(fields=["clustering_run", "level"], name="idx_gcf_run_level"),
            models.Index(fields=["clustering_run", "parent_path"], name="idx_gcf_run_parent"),
        ]

    def __str__(self):
        return self.family_path


class NonRedundantBGCClusteringSnapshot(models.Model):
    """Frozen per-NRB classification at import time, for rollback.

    The HPC importer (``import_clustering_results``) writes one row per
    primary or partial NRB before overwriting the live columns on
    ``NonRedundantBGC``. ``set_active_clustering_run`` reads these to
    restore a previous run's state without recomputing.
    """

    id = models.BigAutoField(primary_key=True)
    clustering_run = models.ForeignKey(
        ClusteringRun,
        on_delete=models.CASCADE,
        related_name="nrb_snapshots",
    )
    nrb = models.ForeignKey(
        "NonRedundantBGC",
        on_delete=models.CASCADE,
        related_name="clustering_snapshots",
    )
    umap_x = models.FloatField(null=True, blank=True)
    umap_y = models.FloatField(null=True, blank=True)
    umap_projected = models.BooleanField(default=False)
    gene_cluster_family = models.CharField(max_length=512, blank=True, default="")
    novelty_score = models.FloatField(null=True, blank=True)
    domain_novelty = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "discovery_nrb_clustering_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["clustering_run", "nrb"],
                name="uniq_snapshot_run_nrb",
            ),
        ]
        indexes = [
            models.Index(fields=["clustering_run"], name="idx_snapshot_run"),
        ]

    def __str__(self):
        return f"snapshot(run={self.clustering_run_id}, nrb={self.nrb_id})"


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


class DashboardCdsChemOnt(models.Model):
    """Deepest ChemOnt class predicted by CHAMOIS for a single CDS.

    The class is chosen with **cross-BGC** evidence: per-BGC ``chamois explain
    --cds`` TSVs are conceptually concatenated and, for each protein, the
    (class, BGC) cell with the largest gene weight is the *argmax*. The protein
    is kept only if ``argmax_weight > 1.0`` AND the BGC-level probability of the
    argmax cell is ``> 0.5``. The reported class is then the **globally
    deepest** descendant of the argmax class whose cross-BGC max gene weight is
    also ``> 1.0`` (ties broken by higher weight); if no descendant qualifies,
    the argmax class itself is reported.

    The same selected class is written to every CDS row of the protein —
    one ``DashboardCdsChemOnt`` per (BGC, protein), since each
    ``DashboardCds`` is scoped to a single BGC.
    """

    id = models.BigAutoField(primary_key=True)
    cds = models.ForeignKey(
        DashboardCds,
        on_delete=models.CASCADE,
        related_name="chemont",
    )
    chemont_id = models.CharField(
        max_length=30,
        help_text="ChemOnt ontology term ID, e.g. CHEMONTID:0000147",
    )
    chemont_name = models.CharField(max_length=255)
    probability = models.FloatField(
        default=0.0,
        help_text="BGC-level probability of the argmax class for this CDS.",
    )
    weight = models.FloatField(
        default=0.0,
        help_text="Gene-specific weight of the deepest selected class.",
    )

    class Meta:
        db_table = "discovery_cds_chemont"
        unique_together = [("cds", "chemont_id")]
        indexes = [
            models.Index(fields=["chemont_id"], name="idx_cdschemont_cid"),
            models.Index(fields=["cds"], name="idx_cdschemont_cds"),
        ]

    def __str__(self):
        return f"{self.chemont_id} ({self.chemont_name})"


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
        ``chemont_ic``            — {chemont_id: IC_value} for semantic similarity.
        ``chemont_sunburst``      — ChemOnt class sunburst node list.
    """

    key = models.CharField(max_length=100, primary_key=True)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_precomputed_stats"

    def __str__(self):
        return self.key


# ── Append-only platform overview snapshots ────────────────────────────────────


class DiscoveryStats(models.Model):
    """Append-only snapshot of high-level Discovery Platform counts.

    Populated by the ``update_discovery_stats`` management command and the
    matching Celery task.  The latest row is surfaced via the
    ``/api/dashboard/stats/`` endpoint and rendered in the Run Query card.
    """

    id = models.AutoField(primary_key=True)
    stats = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_stats"
        ordering = ["-created_at"]

    def __str__(self):
        return f"DiscoveryStats id={self.pk} at {self.created_at.isoformat()}"
