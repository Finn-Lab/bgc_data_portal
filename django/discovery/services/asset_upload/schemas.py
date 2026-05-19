"""Internal dataclasses for the ephemeral asset-upload pipeline.

These mirror the column layout that ``services/ingestion/loader.py``
accepts for the persistent DB pipeline, but are kept entirely in memory.
The asset projection step (``project.py``) reads them, builds virtual NRBs
using the same overlap-chain algorithm as ``non_redundant.py``, and
materialises Redis payloads — nothing here ever touches the ORM.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AssetAssembly:
    assembly_accession: str
    organism_name: str = ""
    source: str = ""
    assembly_type: int = 2
    biome_path: str = ""
    is_type_strain: bool = False
    type_strain_catalog_url: str = ""
    assembly_size_mb: float | None = None
    url: str = ""


@dataclass
class AssetContig:
    assembly_accession: str
    sequence_sha256: str
    accession: str = ""
    length: int = 0
    taxonomy_path: str = ""
    source_contig_id: int | None = None


@dataclass
class AssetDetector:
    name: str
    tool: str
    version: str


@dataclass
class AssetBgc:
    """One BGC prediction row keyed by (contig_sha, start, end, detector_name).

    ``classification_path``/``novelty_score``/``domain_novelty``/``umap_x``/
    ``umap_y``/``gene_cluster_family`` are intentionally left at the inert
    defaults from the TSV — the projection step recomputes them on the fly,
    so anything the user puts there in the upload is ignored.
    """

    contig_sha256: str
    detector_name: str
    start_position: int
    end_position: int
    classification_path: str = ""
    size_kb: float = 0.0
    is_partial: bool = False
    is_validated: bool = False

    @property
    def key(self) -> tuple[str, int, int, str]:
        return (
            self.contig_sha256,
            self.start_position,
            self.end_position,
            self.detector_name,
        )


@dataclass
class AssetCds:
    """One CDS row inside an asset BGC. Identified by parent BGC key + ``protein_id_str``."""

    bgc_key: tuple[str, int, int, str]
    protein_id_str: str
    start_position: int
    end_position: int
    strand: int
    protein_length: int = 0
    gene_caller: str = ""
    cluster_representative: str = ""
    protein_sha256: str = ""
    sequence_zlib_b64: str = ""  # populated from cds_sequences.tsv when present


@dataclass
class AssetDomain:
    """One Pfam/NCBIfam/etc. hit on an asset BGC's CDS.

    The ``cds_protein_id`` matches the parent ``AssetCds.protein_id_str`` —
    the projection step joins on (bgc_key, cds_protein_id) to align
    adjacency anchors with the CDS positions.
    """

    bgc_key: tuple[str, int, int, str]
    cds_protein_id: str
    domain_acc: str
    domain_name: str = ""
    domain_description: str = ""
    ref_db: str = ""
    start_position: int = 0
    end_position: int = 0
    score: float | None = None
    url: str = ""


@dataclass
class AssetNaturalProduct:
    bgc_key: tuple[str, int, int, str]
    name: str
    smiles: str = ""
    np_class_path: str = ""
    structure_svg_base64: str = ""
    morgan_fp_b64: str = ""


@dataclass
class AssetCdsChemOnt:
    """Per-CDS ChemOnt classification (deepest class as emitted by CHAMOIS)."""

    bgc_key: tuple[str, int, int, str]
    protein_id_str: str
    chemont_id: str
    chemont_name: str = ""
    probability: float = 0.0
    weight: float = 0.0


@dataclass
class AssetData:
    """Fully-parsed in-memory asset, ready for the projection step."""

    assemblies: list[AssetAssembly] = field(default_factory=list)
    contigs: list[AssetContig] = field(default_factory=list)
    detectors: list[AssetDetector] = field(default_factory=list)
    bgcs: list[AssetBgc] = field(default_factory=list)
    cds: list[AssetCds] = field(default_factory=list)
    contig_sequences: dict[str, str] = field(default_factory=dict)  # sha256 → zlib-b64
    domains: list[AssetDomain] = field(default_factory=list)
    natural_products: list[AssetNaturalProduct] = field(default_factory=list)
    cds_chemont: list[AssetCdsChemOnt] = field(default_factory=list)

    def assembly_lookup(self) -> dict[str, AssetAssembly]:
        return {a.assembly_accession: a for a in self.assemblies}

    def contig_lookup(self) -> dict[str, AssetContig]:
        return {c.sequence_sha256: c for c in self.contigs}

    def bgcs_by_contig(self) -> dict[str, list[AssetBgc]]:
        out: dict[str, list[AssetBgc]] = {}
        for b in self.bgcs:
            out.setdefault(b.contig_sha256, []).append(b)
        return out

    def domains_by_bgc(self) -> dict[tuple[str, int, int, str], list[AssetDomain]]:
        out: dict[tuple[str, int, int, str], list[AssetDomain]] = {}
        for d in self.domains:
            out.setdefault(d.bgc_key, []).append(d)
        return out

    def cds_by_bgc(self) -> dict[tuple[str, int, int, str], list[AssetCds]]:
        out: dict[tuple[str, int, int, str], list[AssetCds]] = {}
        for c in self.cds:
            out.setdefault(c.bgc_key, []).append(c)
        return out

    def nps_by_bgc(self) -> dict[tuple[str, int, int, str], list[AssetNaturalProduct]]:
        out: dict[tuple[str, int, int, str], list[AssetNaturalProduct]] = {}
        for n in self.natural_products:
            out.setdefault(n.bgc_key, []).append(n)
        return out


# ── Limits (also referenced by validate.py) ──────────────────────────────────

MAX_TARBALL_BYTES = 100 * 1024 * 1024  # 100 MB decompressed
MAX_TARBALL_ENTRIES = 500
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per inner TSV
MAX_BGC_ROWS = 500
MAX_CDS_ROWS = 50_000
MAX_DOMAIN_ROWS = 200_000

REQUIRED_FILES: tuple[str, ...] = (
    "assemblies.tsv",
    "contigs.tsv",
    "bgcs.tsv",
    "detectors.tsv",
)
OPTIONAL_FILES: tuple[str, ...] = (
    "cds.tsv",
    "cds_sequences.tsv",
    "contig_sequences.tsv",
    "domains.tsv",
    "natural_products.tsv",
    "cds_chemont.tsv",
)
ALLOWED_FILES: frozenset[str] = frozenset(REQUIRED_FILES + OPTIONAL_FILES)

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "assemblies.tsv": ("assembly_accession",),
    "contigs.tsv": ("assembly_accession", "sequence_sha256"),
    "detectors.tsv": ("name", "tool", "version"),
    "bgcs.tsv": (
        "contig_sha256",
        "detector_name",
        "start_position",
        "end_position",
    ),
    "cds.tsv": (
        "contig_sha256",
        "bgc_start",
        "bgc_end",
        "detector_name",
        "protein_id_str",
        "start_position",
        "end_position",
        "strand",
    ),
    "cds_sequences.tsv": (
        "contig_sha256",
        "bgc_start",
        "bgc_end",
        "detector_name",
        "protein_id_str",
        "sequence_base64",
    ),
    "contig_sequences.tsv": ("contig_sha256", "sequence_base64"),
    "domains.tsv": (
        "contig_sha256",
        "bgc_start",
        "bgc_end",
        "detector_name",
        "protein_id_str",
        "domain_acc",
    ),
    "natural_products.tsv": (
        "contig_sha256",
        "bgc_start",
        "bgc_end",
        "detector_name",
        "name",
    ),
    "cds_chemont.tsv": (
        "contig_sha256",
        "bgc_start",
        "bgc_end",
        "detector_name",
        "protein_id_str",
        "chemont_id",
        "chemont_name",
    ),
}
