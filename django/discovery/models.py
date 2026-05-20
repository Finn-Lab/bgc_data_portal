"""Discovery Platform models — iBGC-first, contig-anchored CDS/domains.

Core entity hierarchy (top-down):

    DashboardAssembly
        └─ DashboardContig
            ├─ ContigCds                 (CDS on contig; range-indexed)
            │     ├─ ContigDomain        (domain hits; denormalised contig FK)
            │     └─ CdsChemOnt          (ChemOnt class per CDS)
            ├─ ConsensusBgc (cBGC)       (chained-overlap region; MGYB-XXXXXX)
            │     └─ IntegratedBgc (iBGC) (core operational unit; MGYB-XXXXXX-YY)
            │           ├─ SourceBgcPrediction (per-tool prediction)
            │           └─ IbgcNaturalProduct  (NP claim, deduped at ingest)
            └─ (sequences on demand)

Hierarchical fields (taxonomy_path, biome_path, classification_path,
np_class_path, gene_cluster_family) store dot-delimited ltree paths.

The migration installs ``ltree`` and ``btree_gist`` extensions and creates
GiST indexes on the int4range columns so ``contig_id WITH =, *_range WITH &&``
exclusion constraints enforce iBGC disjointness and cBGC disjointness in
the database, and so range overlap queries hit a GiST index.

iBGCs are strictly disjoint within a cBGC; CDS membership in an iBGC is
decided by range overlap (``ContigCds.cds_range && IntegratedBgc.bgc_range``)
on the same contig.
"""

import zlib

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import IntegerRangeField
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
    """Denormalised assembly row: identity + biome + precomputed scores."""

    id = models.BigAutoField(primary_key=True)

    assembly_accession = models.CharField(max_length=255, unique=True, db_index=True)
    organism_name = models.CharField(max_length=255, blank=True, default="")

    source = models.ForeignKey(
        AssemblySource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assemblies",
        db_index=True,
    )

    assembly_type = models.SmallIntegerField(
        choices=AssemblyType.choices,
        default=AssemblyType.GENOME,
        db_index=True,
    )

    biome_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. root.Environmental.Terrestrial.Soil",
    )

    is_type_strain = models.BooleanField(default=False, db_index=True)
    type_strain_catalog_url = models.URLField(blank=True, default="")
    assembly_size_mb = models.FloatField(null=True, blank=True)
    url = models.URLField(max_length=512, blank=True, default="")

    # Precomputed scores (denormalised from per-iBGC stats)
    bgc_count = models.IntegerField(default=0)
    l1_class_count = models.IntegerField(default=0)
    bgc_diversity_score = models.FloatField(default=0.0)
    bgc_novelty_score = models.FloatField(default=0.0)
    bgc_density = models.FloatField(default=0.0)
    taxonomic_novelty = models.FloatField(default=0.0)

    pctl_diversity = models.FloatField(default=0.0)
    pctl_novelty = models.FloatField(default=0.0)
    pctl_density = models.FloatField(default=0.0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_assembly"
        indexes = [
            models.Index(fields=["-bgc_novelty_score"], name="idx_da_novelty_desc"),
            models.Index(fields=["-bgc_diversity_score"], name="idx_da_diversity_desc"),
            models.Index(fields=["-bgc_density"], name="idx_da_density_desc"),
            models.Index(fields=["organism_name"], name="idx_da_organism"),
            models.Index(fields=["biome_path"], name="idx_da_biome"),
        ]

    def __str__(self):
        return self.assembly_accession


# ── Contig ──────────────────────────────────────────────────────────────────────


class DashboardContig(models.Model):
    """Contig within an assembly — CDS, cBGCs and iBGCs hang off this."""

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

    taxonomy_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. Bacteria.Actinomycetota.Actinomycetia...",
    )

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
    """BGC detection tool + version lookup."""

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


# ── Accession Registry ────────────────────────────────────────────────────────


class AccessionEntityType(models.TextChoices):
    CBGC = "cbgc", "Consensus BGC"
    IBGC = "ibgc", "Integrated BGC"


class AccessionRegistry(models.Model):
    """Stable-forever accession ledger for cBGCs and iBGCs.

    One row per ever-assigned accession. Identity tuple is
    ``(entity_type, contig_accession, start_pos, end_pos)`` — the same
    entity reproduced after a rebuild reuses its accession. Accessions
    never get reassigned; when an entity disappears between rebuilds,
    ``current_cbgc`` / ``current_ibgc`` is NULLed and the accession is
    tombstoned (the resolve endpoint returns 410 for it).

    cBGC accessions: ``MGYB-XXXXXX`` (6 Crockford base32 chars).
    iBGC accessions: ``MGYB-XXXXXX-YY`` (cBGC accession + 2-char suffix).
    """

    accession = models.CharField(max_length=20, primary_key=True)
    entity_type = models.CharField(
        max_length=10,
        choices=AccessionEntityType.choices,
        db_index=True,
    )
    contig_accession = models.CharField(max_length=255, db_index=True)
    start_pos = models.IntegerField()
    end_pos = models.IntegerField()

    current_cbgc = models.ForeignKey(
        "ConsensusBgc",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registry_entries",
    )
    current_ibgc = models.ForeignKey(
        "IntegratedBgc",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registry_entries",
    )

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_accession_registry"
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "contig_accession", "start_pos", "end_pos"],
                name="uniq_registry_identity",
            ),
        ]
        indexes = [
            models.Index(
                fields=["entity_type", "contig_accession", "start_pos", "end_pos"],
                name="idx_registry_identity",
            ),
        ]

    @property
    def is_tombstoned(self) -> bool:
        if self.entity_type == AccessionEntityType.CBGC:
            return self.current_cbgc_id is None
        return self.current_ibgc_id is None

    def __str__(self):
        return self.accession


class AccessionAlias(models.Model):
    """Historical accession aliases — old → current registry entry.

    Populated when (a) a pre-refactor ``MGYB{id:08}`` cBGC accession must
    map to a new ``MGYB-XXXXXX`` accession, and (b) any future renames.
    """

    id = models.AutoField(primary_key=True)
    alias_accession = models.CharField(max_length=50, unique=True, db_index=True)
    registry = models.ForeignKey(
        AccessionRegistry,
        on_delete=models.CASCADE,
        related_name="aliases",
    )

    class Meta:
        db_table = "discovery_accession_alias"

    def __str__(self):
        return f"{self.alias_accession} → {self.registry_id}"


# ── Consensus BGC (cBGC) ──────────────────────────────────────────────────────


class ConsensusBgc(models.Model):
    """Aggregated genomic region on a contig — the chained-overlap envelope
    that contains one or more iBGCs.

    Accession ``MGYB-XXXXXX`` is stable forever via ``AccessionRegistry``.
    Disjointness across cBGCs on the same contig is enforced by an
    exclusion constraint on ``(contig_id, bgc_range)``.
    """

    id = models.BigAutoField(primary_key=True)
    accession = models.CharField(max_length=20, unique=True, db_index=True)
    contig = models.ForeignKey(
        DashboardContig,
        on_delete=models.CASCADE,
        related_name="cbgcs",
        db_index=True,
    )
    bgc_range = IntegerRangeField(
        help_text="Half-open [start, end) genomic span; lower = 1-based start, upper = exclusive end",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_cbgc"
        constraints = [
            ExclusionConstraint(
                name="excl_cbgc_overlap",
                expressions=[
                    ("contig", "="),
                    ("bgc_range", "&&"),
                ],
            ),
        ]

    @property
    def start_position(self) -> int:
        return self.bgc_range.lower

    @property
    def end_position(self) -> int:
        return self.bgc_range.upper - 1

    def __str__(self):
        return self.accession


# ── Integrated BGC (iBGC) — core operational unit ─────────────────────────────


class IntegratedBgc(models.Model):
    """Integrated BGC — the core operational unit of the platform.

    Sits inside exactly one ``ConsensusBgc``. iBGCs within the same cBGC
    are strictly disjoint (DB-enforced via exclusion constraint).

    Accession ``MGYB-XXXXXX-YY`` is stable forever via ``AccessionRegistry``.

    CDS membership is decided by range overlap on the contig:
        ``ContigCds.cds_range && IntegratedBgc.bgc_range``
    Domain hits inherit from their CDS.

    Built from ``SourceBgcPrediction`` rows:
      * Validated predictions become standalone iBGCs regardless of tool
        or partial flag — ground truth, never merged with predictions.
      * Non-validated GECCO and SanntiS predictions on the same contig
        merge via transitive interval overlap (any positive intersection
        joins a component, regardless of ``is_partial``). The merged
        interval spans ``min(starts) → max(ends)``.
      * For each chain iBGC above, any non-validated antiSMASH prediction
        overlapping it has ``'antiSMASH'`` added to ``source_tools`` and
        gets ``integrated_bgc`` set to that iBGC (so ``claimed_by_tools``
        attribution is preserved). antiSMASH coordinates do not widen the
        chain interval.
      * Non-validated antiSMASH predictions that do not overlap any
        already-built iBGC on the same contig become their own iBGC.

    Clustering writes ``gene_cluster_family``, ``umap_x``/``umap_y``,
    ``novelty_score`` and ``domain_novelty`` here. Source predictions do
    not duplicate these — they are derived from ``integrated_bgc`` on
    read.
    """

    id = models.BigAutoField(primary_key=True)
    accession = models.CharField(max_length=20, unique=True, db_index=True)
    cbgc = models.ForeignKey(
        ConsensusBgc,
        on_delete=models.CASCADE,
        related_name="ibgcs",
        db_index=True,
    )
    contig = models.ForeignKey(
        DashboardContig,
        on_delete=models.CASCADE,
        related_name="ibgcs",
        db_index=True,
        help_text="Denormalised from cbgc.contig for fast range-overlap queries",
    )
    bgc_range = IntegerRangeField(
        help_text="Half-open [start, end) genomic span on the contig",
    )

    source_tools = models.JSONField(
        default=list,
        help_text="Sorted, deduped tool names contributing, e.g. ['GECCO','SanntiS']",
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
            "iBGC coordinates (partials reclassified via KNN). False when the "
            "iBGC was included in the main UMAP layout."
        ),
    )
    novelty_score = models.FloatField(
        null=True,
        blank=True,
        help_text="1 − max composite-Dice similarity to the nearest validated iBGC.",
    )
    domain_novelty = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "Fraction of this iBGC's domains not shared by any other iBGC of the "
            "same leaf GCF. NULL for singleton GCFs and for iBGCs without any "
            "domains of the selected sources."
        ),
    )
    classification_run = models.ForeignKey(
        "ClusteringRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ibgcs",
    )
    classified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_ibgc"
        constraints = [
            ExclusionConstraint(
                name="excl_ibgc_overlap_in_cbgc",
                expressions=[
                    ("cbgc", "="),
                    ("bgc_range", "&&"),
                ],
            ),
        ]
        indexes = [
            models.Index(fields=["gene_cluster_family"], name="idx_ibgc_gcf"),
        ]

    @property
    def start_position(self) -> int:
        return self.bgc_range.lower

    @property
    def end_position(self) -> int:
        return self.bgc_range.upper - 1

    @property
    def size_kb(self) -> float:
        return (self.bgc_range.upper - self.bgc_range.lower) / 1000.0

    def __str__(self):
        return self.accession


# ── Source BGC prediction (per-tool, per-contig) ──────────────────────────────


class SourceBgcPrediction(models.Model):
    """One BGC prediction emitted by one detection tool on one contig.

    Provenance row, not a CDS/domain owner. CDS and domains live on the
    contig and are reached from an iBGC via range overlap. A source
    prediction's ``claimed_by_tools`` contribution is whatever overlap its
    ``bgc_range`` has with each CDS in its owning iBGC.

    Scoring, classification and UMAP fields live on ``IntegratedBgc``; do
    not duplicate them here. ``integrated_bgc`` is NULL only for partials
    or predictions that fail to land in any iBGC at build time.

    ``prediction_accession`` is derived at ingest as
    ``{cbgc.accession}.{detector.tool_name_code}.{bgc_number:02d}``,
    e.g. ``MGYB-ABC123.ANT.01``.
    """

    id = models.BigAutoField(primary_key=True)

    assembly = models.ForeignKey(
        DashboardAssembly,
        on_delete=models.CASCADE,
        related_name="source_bgcs",
        db_index=True,
    )
    contig = models.ForeignKey(
        DashboardContig,
        on_delete=models.CASCADE,
        related_name="source_bgcs",
        db_index=True,
    )

    prediction_accession = models.CharField(max_length=50, db_index=True)
    bgc_range = IntegerRangeField(help_text="Half-open [start, end) genomic span on the contig")

    is_partial = models.BooleanField(default=False)
    is_validated = models.BooleanField(default=False)

    detector = models.ForeignKey(
        DashboardDetector,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_bgcs",
        db_index=True,
    )

    cbgc = models.ForeignKey(
        ConsensusBgc,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_bgcs",
        db_index=True,
    )
    bgc_number = models.PositiveSmallIntegerField(
        default=0,
        help_text="2-digit incremental within (cbgc, detector); used in prediction_accession",
    )

    integrated_bgc = models.ForeignKey(
        IntegratedBgc,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_predictions",
        db_index=True,
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_source_bgc"
        constraints = [
            ExclusionConstraint(
                name="excl_source_bgc_overlap_per_detector",
                expressions=[
                    ("contig", "="),
                    ("detector", "="),
                    ("bgc_range", "&&"),
                ],
            ),
        ]
        indexes = [
            models.Index(fields=["assembly"], name="idx_sbgc_assembly"),
            models.Index(fields=["integrated_bgc"], name="idx_sbgc_ibgc"),
        ]

    @property
    def start_position(self) -> int:
        return self.bgc_range.lower

    @property
    def end_position(self) -> int:
        return self.bgc_range.upper - 1

    @property
    def size_kb(self) -> float:
        return (self.bgc_range.upper - self.bgc_range.lower) / 1000.0

    def __str__(self):
        return self.prediction_accession


# ── Contig CDS ────────────────────────────────────────────────────────────────


class ContigCds(models.Model):
    """A coding sequence on a contig.

    CDS live at the contig level (not per-BGC). The same gene called by
    multiple BGC tools is stored once. iBGC region views reach CDS via
    range overlap:
        ``ContigCds.objects.filter(contig=ibgc.contig,
                                   cds_range__overlap=ibgc.bgc_range)``
    """

    id = models.BigAutoField(primary_key=True)
    contig = models.ForeignKey(
        DashboardContig,
        on_delete=models.CASCADE,
        related_name="cds_list",
        db_index=True,
    )
    cds_range = IntegerRangeField(help_text="Half-open [start, end) genomic span on the contig")
    strand = models.SmallIntegerField()

    protein_id_str = models.CharField(
        max_length=255,
        help_text="Display identifier (mgyp or protein_identifier)",
    )
    protein_length = models.IntegerField(default=0)
    gene_caller = models.CharField(max_length=100, blank=True, default="")
    cluster_representative = models.CharField(max_length=64, blank=True, default="")
    protein_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="SHA-256 hash of the amino-acid sequence (pyhmmer search-index key)",
    )

    class Meta:
        db_table = "discovery_cds"
        constraints = [
            ExclusionConstraint(
                name="uniq_cds_contig_range_strand",
                expressions=[
                    ("contig", "="),
                    ("cds_range", "="),
                    ("strand", "="),
                ],
            ),
        ]
        indexes = [
            models.Index(fields=["protein_sha256"], name="idx_dcds_prot_sha256"),
        ]

    @property
    def start_position(self) -> int:
        return self.cds_range.lower

    @property
    def end_position(self) -> int:
        return self.cds_range.upper - 1

    def __str__(self):
        return f"CDS {self.protein_id_str} on contig {self.contig_id}"


class CdsSequence(models.Model):
    """On-demand amino-acid sequence for a CDS — zlib-compressed."""

    cds = models.OneToOneField(
        ContigCds,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="seq",
    )
    data = models.BinaryField(help_text="zlib-compressed amino-acid sequence")

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


# ── Contig Domain ─────────────────────────────────────────────────────────────


class ContigDomain(models.Model):
    """Domain hit on a contig CDS.

    The ``contig`` FK is denormalised from ``cds.contig`` so iBGC-scope
    domain queries can range-filter without a join:
        ``ContigDomain.objects.filter(cds__contig=ibgc.contig,
                                      cds__cds_range__overlap=ibgc.bgc_range)``
    Positions are protein-relative (amino-acid coordinates).
    """

    id = models.BigAutoField(primary_key=True)
    cds = models.ForeignKey(
        ContigCds,
        on_delete=models.CASCADE,
        related_name="domains",
    )
    contig = models.ForeignKey(
        DashboardContig,
        on_delete=models.CASCADE,
        related_name="domains",
        db_index=True,
    )

    domain_acc = models.CharField(max_length=50, db_index=True)
    domain_name = models.CharField(max_length=255)
    domain_description = models.TextField(blank=True, default="")
    ref_db = models.CharField(max_length=50, blank=True, default="")

    go_slim = models.JSONField(default=list, blank=True)
    interpro_entry_acc = models.CharField(max_length=20, blank=True, default="")
    interpro_entry_description = models.CharField(max_length=255, blank=True, default="")
    go_terms = models.JSONField(default=list, blank=True)

    # Protein-relative (amino-acid) coordinates of the hit
    start_position = models.IntegerField(default=0)
    end_position = models.IntegerField(default=0)
    score = models.FloatField(null=True, blank=True)
    url = models.URLField(max_length=512, blank=True, default="")

    class Meta:
        db_table = "discovery_domain_hit"
        constraints = [
            models.UniqueConstraint(
                fields=["cds", "domain_acc", "start_position", "end_position"],
                name="uniq_domain_cds_acc_pos",
            ),
        ]
        indexes = [
            models.Index(fields=["domain_acc", "contig"], name="idx_dom_acc_contig"),
            models.Index(fields=["contig", "domain_acc"], name="idx_dom_contig_acc"),
            models.Index(
                fields=["contig", "ref_db", "domain_acc"],
                name="idx_dom_contig_ref_acc",
            ),
        ]

    def __str__(self):
        return f"{self.domain_acc} on CDS {self.cds_id}"


# ── CDS ChemOnt ───────────────────────────────────────────────────────────────


class CdsChemOnt(models.Model):
    """Deepest ChemOnt class predicted by CHAMOIS for a single CDS.

    The class is chosen with cross-iBGC evidence: per-iBGC ``chamois explain
    --cds`` outputs are conceptually concatenated and, for each protein,
    the (class, iBGC) cell with the largest gene weight is the argmax. The
    protein is kept only if ``argmax_weight > 1.0`` AND the iBGC-level
    probability of the argmax cell is ``> 0.5``. The reported class is the
    globally deepest descendant of the argmax class whose cross-iBGC max
    gene weight is also ``> 1.0`` (ties broken by higher weight); else the
    argmax class itself.
    """

    id = models.BigAutoField(primary_key=True)
    cds = models.ForeignKey(
        ContigCds,
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
        help_text="iBGC-level probability of the argmax class for this CDS.",
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


# ── Clustering ────────────────────────────────────────────────────────────────


class ClusteringRun(models.Model):
    """One iBGC composite-Dice → KNN graph → hierarchical CPM Leiden run.

    Parameters + counts only. The hierarchy itself lives in ``DashboardGCF``
    rows; per-iBGC leaf paths live on ``IntegratedBgc.gene_cluster_family``.
    Re-running with identical inputs yields the same ``sha256`` and so the
    same ``pk`` (idempotent via ``update_or_create``).
    """

    created_at = models.DateTimeField(auto_now_add=True)

    domain_sources = models.JSONField(
        default=list,
        help_text="Domain ref_db sources used (upper-case), e.g. ['PFAM','NCBIFAM']",
    )
    DOMAIN_VOCAB_RAW = "RAW"
    DOMAIN_VOCAB_IPR_PROJECTED = "IPR_PROJECTED"
    DOMAIN_VOCAB_CHOICES = (
        (DOMAIN_VOCAB_RAW, "Raw signature accessions"),
        (DOMAIN_VOCAB_IPR_PROJECTED, "IPR entry when available, else signature"),
    )
    domain_vocab = models.CharField(
        max_length=20,
        choices=DOMAIN_VOCAB_CHOICES,
        default=DOMAIN_VOCAB_IPR_PROJECTED,
    )
    score_weights = models.JSONField(
        default=list,
        help_text="(w_domain, w_adjacency) for the composite Dice score, e.g. [0.5, 0.5]",
    )
    knn_k = models.PositiveSmallIntegerField()
    leiden_resolutions = models.JSONField(
        default=list,
        help_text="CPM resolution_parameter values, coarsest first",
    )
    seed = models.PositiveIntegerField(default=42)

    n_proteins = models.PositiveIntegerField(default=0)
    n_ibgcs = models.PositiveIntegerField(default=0)
    n_levels = models.PositiveSmallIntegerField(default=0)
    n_root_communities = models.PositiveIntegerField(default=0)
    n_leaf_communities = models.PositiveIntegerField(default=0)

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


class DashboardGCF(models.Model):
    """A node in the hierarchical Leiden tree for a ``ClusteringRun``.

    One row per node at every level. The full ``family_path`` ltree string
    identifies the node uniquely; ``parent_path`` points at the immediate
    parent (empty string for level-0 roots).
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
    representative_ibgc = models.ForeignKey(
        IntegratedBgc,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="represented_gcfs",
    )

    member_count = models.IntegerField(
        default=0,
        help_text="Total iBGCs whose leaf path is a descendant of this node (or equal at leaves)",
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


class IbgcClusteringSnapshot(models.Model):
    """Frozen per-iBGC classification at import time, for rollback.

    The HPC importer writes one row per primary or partial iBGC before
    overwriting the live columns on ``IntegratedBgc``. The
    ``set_active_clustering_run`` command reads these to restore a previous
    run's state without recomputing.
    """

    id = models.BigAutoField(primary_key=True)
    clustering_run = models.ForeignKey(
        ClusteringRun,
        on_delete=models.CASCADE,
        related_name="ibgc_snapshots",
    )
    ibgc = models.ForeignKey(
        IntegratedBgc,
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
        db_table = "discovery_ibgc_clustering_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["clustering_run", "ibgc"],
                name="uniq_snapshot_run_ibgc",
            ),
        ]
        indexes = [
            models.Index(fields=["clustering_run"], name="idx_snapshot_run"),
        ]

    def __str__(self):
        return f"snapshot(run={self.clustering_run_id}, ibgc={self.ibgc_id})"


# ── iBGC Natural Product ──────────────────────────────────────────────────────


class IbgcNaturalProduct(models.Model):
    """Characterised natural product claimed by an iBGC.

    Re-FK'd from the per-source-BGC model — one row per iBGC × NP.
    Multiple tools predicting the same NP for the same iBGC collapse to
    one row at ingest, deduped on ``(ibgc, dedup_hash)`` where
    ``dedup_hash = sha256(name|smiles)``.
    """

    id = models.BigAutoField(primary_key=True)
    ibgc = models.ForeignKey(
        IntegratedBgc,
        on_delete=models.CASCADE,
        related_name="natural_products",
    )
    name = models.CharField(max_length=255)
    smiles = models.TextField(blank=True, default="")
    dedup_hash = models.CharField(
        max_length=64,
        help_text="sha256(name|smiles) hex digest; used for ingest-time dedup",
    )

    np_class_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="ltree dot-path, e.g. Polyketide.Macrolide.Erythromycin",
    )
    structure_svg_base64 = models.TextField(blank=True, default="")
    morgan_fp = models.BinaryField(null=True, blank=True)

    class Meta:
        db_table = "discovery_ibgc_natural_product"
        constraints = [
            models.UniqueConstraint(
                fields=["ibgc", "dedup_hash"],
                name="uniq_np_ibgc_dedup",
            ),
        ]
        indexes = [
            models.Index(fields=["np_class_path"], name="idx_dnp_class_path"),
            models.Index(fields=["ibgc"], name="idx_dnp_ibgc"),
        ]

    def __str__(self):
        return self.name


# ── Catalog tables with precomputed counts ───────────────────────────────────


class DashboardBgcClass(models.Model):
    """BGC classification label with precomputed iBGC count."""

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True, db_index=True)
    bgc_count = models.IntegerField(
        default=0,
        help_text="Number of iBGCs in this class (column name kept for API parity)",
    )

    class Meta:
        db_table = "discovery_bgc_class"

    def __str__(self):
        return self.name


class DashboardDomain(models.Model):
    """Domain catalog entry with precomputed iBGC count."""

    id = models.AutoField(primary_key=True)
    acc = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    ref_db = models.CharField(max_length=50, blank=True, default="")
    description = models.TextField(blank=True, default="")
    bgc_count = models.IntegerField(
        default=0,
        help_text="Number of iBGCs whose domains include this acc (column name kept for API parity)",
    )

    class Meta:
        db_table = "discovery_domain"
        indexes = [
            models.Index(fields=["-bgc_count"], name="idx_dd_count_desc"),
        ]

    def __str__(self):
        return f"{self.acc} ({self.name})"


# ── Precomputed statistics ───────────────────────────────────────────────────


class PrecomputedStats(models.Model):
    """Precomputed aggregate statistics to avoid full-table scans.

    Keys include ``genome_global``, ``bgc_global``, ``taxonomy_sunburst``,
    ``np_class_sunburst``, ``bgc_class_distribution``, ``chemont_ic``,
    ``chemont_sunburst``.
    """

    key = models.CharField(max_length=100, primary_key=True)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_precomputed_stats"

    def __str__(self):
        return self.key


# ── Append-only platform overview snapshots ──────────────────────────────────


class DiscoveryStats(models.Model):
    """Append-only snapshot of high-level Discovery Platform counts."""

    id = models.AutoField(primary_key=True)
    stats = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discovery_stats"
        ordering = ["-created_at"]

    def __str__(self):
        return f"DiscoveryStats id={self.pk} at {self.created_at.isoformat()}"
