"""Project parsed asset data onto the latest ClusteringRun.

Pipeline:

1. Walk asset BGCs per contig and apply the canonical overlap-chain rules
   (validated standalones, GECCO+SanntiS chains, antiSMASH absorb-or-emit)
   via the shared :func:`integrated._build_ibgcs_for_contig`. Each
   resulting iBGC gets a negative integer id and is materialised as a
   ``VirtualIbgc`` carrying its member BGCs, CDS rows, domains, and NPs.

2. Load the most recent ``ClusteringRun``'s scoring cache from disk —
   primary domain matrix, primary adjacency-pair matrix, vocabularies,
   per-row leaf paths.

3. Build the asset's domain + adjacency-pair matrices on the same column
   space, stack them under the primary matrices, run composite-Dice
   similarity, take the top-K nearest primary neighbours per virtual iBGC
   and compute:

   * ``gene_cluster_family`` — weighted-vote leaf path of the K neighbours
   * ``umap_x`` / ``umap_y`` — similarity-weighted average of neighbours'
     coordinates
   * ``novelty_score``       — ``1 − max(sim to validated primary iBGC)``
   * ``domain_novelty``      — fraction of this iBGC's domains not present
     in any primary member of the inherited leaf GCF

   iBGCs without any source-vocabulary overlap keep ``None``/``""`` for the
   four quantities — they still appear in the roster, just dimmed on the
   maps.

4. Materialise per-iBGC Redis payloads (manifest, roster rows, IbgcDetail,
   region, architecture) under the ``asset:{token}:*`` keyspace.
"""

from __future__ import annotations

import base64
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from django.conf import settings

from discovery.services.go_slim import go_slim_for_terms

from . import cache as asset_cache
from .matrices import (
    DEFAULT_DOMAIN_SOURCES,
    build_asset_adjacency_pair_matrix,
    build_asset_domain_matrix,
)
from .schemas import (
    AssetBgc,
    AssetCds,
    AssetCdsChemOnt,
    AssetData,
    AssetDomain,
    AssetNaturalProduct,
)

log = logging.getLogger(__name__)

KNN_K = 5
MIN_TOTAL_SIMILARITY = 0.1


@dataclass
class VirtualIbgc:
    """One ephemeral iBGC built from the asset, with everything its detail /
    region / architecture payloads need pre-joined."""

    neg_id: int  # negative integer id (-1, -2, …)
    contig_sha256: str
    contig_accession: str
    assembly_accession: str
    organism_name: str
    is_type_strain: bool
    start_position: int
    end_position: int
    source_tools: list[str]
    member_bgcs: list[AssetBgc]
    is_partial: bool
    is_validated: bool
    cds: list[AssetCds] = field(default_factory=list)
    domains: list[AssetDomain] = field(default_factory=list)
    natural_products: list[AssetNaturalProduct] = field(default_factory=list)
    cds_chemont: list[AssetCdsChemOnt] = field(default_factory=list)

    # Derived during projection
    umap_x: float | None = None
    umap_y: float | None = None
    umap_projected: bool = False
    novelty_score: float | None = None
    domain_novelty: float | None = None
    gene_cluster_family: str = ""

    @property
    def size_kb(self) -> float:
        return round((self.end_position - self.start_position) / 1000.0, 3)

    @property
    def label(self) -> str:
        return f"iBGC-A{abs(self.neg_id)}"


# ── Step 1: build virtual iBGCs from asset rows ─────────────────────────────


def build_virtual_ibgcs(data: AssetData) -> list[VirtualIbgc]:
    """Return the asset's virtual iBGCs with negative ids assigned.

    Reuses the canonical overlap-chain algorithm from
    :func:`discovery.services.clustering.integrated._build_ibgcs_for_contig`
    by giving each asset BGC a transient positive integer id, mapping back
    after the chains are formed.
    """
    from discovery.services.clustering.integrated import (
        _build_ibgcs_for_contig,
    )

    asm_lookup = data.assembly_lookup()
    contig_lookup = data.contig_lookup()
    detector_tool = {d.name: d.tool for d in data.detectors}
    bgcs_by_contig = data.bgcs_by_contig()
    cds_by_bgc = data.cds_by_bgc()
    domains_by_bgc = data.domains_by_bgc()
    nps_by_bgc = data.nps_by_bgc()
    cds_chemont_by_bgc_protein: dict[
        tuple[tuple[str, int, int, str], str], AssetCdsChemOnt
    ] = {}
    for cls in data.cds_chemont:
        cds_chemont_by_bgc_protein[(cls.bgc_key, cls.protein_id_str)] = cls

    virtual: list[VirtualIbgc] = []
    next_neg_id = -1

    for contig_sha, bgcs in bgcs_by_contig.items():
        contig = contig_lookup.get(contig_sha)
        if contig is None:
            continue
        assembly = asm_lookup.get(contig.assembly_accession)
        organism = assembly.organism_name if assembly else ""
        is_type_strain = bool(assembly.is_type_strain) if assembly else False

        # Build rows shaped like the persistent path expects, using array
        # indices as transient bgc_ids so we can map back to the source rows.
        id_to_bgc: dict[int, AssetBgc] = {i: b for i, b in enumerate(bgcs)}
        rows = [
            (
                i,
                b.start_position,
                b.end_position,
                detector_tool.get(b.detector_name, ""),
                b.is_partial,
                b.is_validated,
            )
            for i, b in id_to_bgc.items()
        ]
        ibgc_tuples, _absorbed, _validated_standalones = _build_ibgcs_for_contig(
            contig_id=0,  # unused
            rows=rows,
        )

        for interval_start, interval_end, source_tools, member_ids in ibgc_tuples:
            members = [id_to_bgc[i] for i in member_ids]
            cds_rows: list[AssetCds] = []
            dom_rows: list[AssetDomain] = []
            np_rows: list[AssetNaturalProduct] = []
            cds_chemont_rows: list[AssetCdsChemOnt] = []
            for b in members:
                bcds = cds_by_bgc.get(b.key, [])
                cds_rows.extend(bcds)
                dom_rows.extend(domains_by_bgc.get(b.key, []))
                np_rows.extend(nps_by_bgc.get(b.key, []))
                for c in bcds:
                    hit = cds_chemont_by_bgc_protein.get((b.key, c.protein_id_str))
                    if hit is not None:
                        cds_chemont_rows.append(hit)

            is_partial = all(m.is_partial for m in members) and not any(
                m.is_validated for m in members
            )
            is_validated = any(m.is_validated for m in members)

            vibgc = VirtualIbgc(
                neg_id=next_neg_id,
                contig_sha256=contig_sha,
                contig_accession=contig.accession,
                assembly_accession=contig.assembly_accession,
                organism_name=organism,
                is_type_strain=is_type_strain,
                start_position=interval_start,
                end_position=interval_end,
                source_tools=sorted(source_tools),
                member_bgcs=members,
                is_partial=is_partial,
                is_validated=is_validated,
                cds=cds_rows,
                domains=dom_rows,
                natural_products=np_rows,
                cds_chemont=cds_chemont_rows,
            )
            virtual.append(vibgc)
            next_neg_id -= 1

    log.info("build_virtual_ibgcs: built %d virtual iBGCs", len(virtual))
    return virtual


# ── Step 2: load primary scoring cache + Step 3: project ───────────────────


def _latest_clustering_run():
    """Return the most-recent ``ClusteringRun`` or ``None`` if none exist."""
    from discovery.models import ClusteringRun

    return ClusteringRun.objects.order_by("-created_at").first()


def _project_against_run(
    virtual_ibgcs: list[VirtualIbgc],
    run,
) -> None:
    """Fill ``umap_x/y``, ``gene_cluster_family``, ``novelty_score``, and
    ``domain_novelty`` on each virtual iBGC by KNN-projecting against the
    primary iBGCs of ``run``.

    Mutates ``virtual_ibgcs`` in place. Virtual iBGCs with no source-vocab
    overlap with the primary matrix are left unprojected (the four fields
    stay at their default ``None`` / ``""``).
    """
    if not virtual_ibgcs:
        return

    import numpy as np
    import scipy.sparse as sp

    from discovery.models import IntegratedBgc, SourceBgcPrediction
    from discovery.services.clustering.bgc_similarity import (
        compute_composite_similarity,
    )
    from discovery.services.clustering.ibgc_scoring import load_scoring_cache

    sources = tuple(run.domain_sources) or DEFAULT_DOMAIN_SOURCES
    weights = tuple(run.score_weights) if run.score_weights else (0.5, 0.5)
    artifacts_dir = settings.CLUSTERING_ARTIFACTS_DIR / run.sha256[:12]

    try:
        cache_payload = load_scoring_cache(artifacts_dir)
    except FileNotFoundError as exc:
        log.warning(
            "Scoring cache missing at %s — virtual iBGCs cannot be projected (%s)",
            artifacts_dir,
            exc,
        )
        return

    M_dom_pri = cache_payload["M_domains"]
    M_pair_pri = cache_payload["M_pairs"]
    pri_row_ids = cache_payload["ibgc_ids"]
    dom_accs = cache_payload["domain_accs"].tolist()
    pair_vocab = cache_payload["pair_vocab"].tolist()
    pri_leaf_paths = list(cache_payload["leaf_paths"])
    n_primary = M_dom_pri.shape[0]

    if n_primary == 0:
        log.warning("Scoring cache has no primary rows — skipping projection")
        return

    # Primary metadata for coord averaging + leaf voting.
    primary_meta = {
        ibgc.id: (ibgc.umap_x, ibgc.umap_y, ibgc.gene_cluster_family or "")
        for ibgc in IntegratedBgc.objects.filter(
            id__in=[int(x) for x in pri_row_ids.tolist()]
        ).only("id", "umap_x", "umap_y", "gene_cluster_family")
    }
    pri_coords = np.array(
        [
            [
                primary_meta.get(int(x), (0.0, 0.0, ""))[0] or 0.0,
                primary_meta.get(int(x), (0.0, 0.0, ""))[1] or 0.0,
            ]
            for x in pri_row_ids.tolist()
        ],
        dtype=np.float32,
    )
    pri_id_to_row = {int(x): i for i, x in enumerate(pri_row_ids.tolist())}

    validated_ibgc_ids = set(
        SourceBgcPrediction.objects.filter(
            is_validated=True, integrated_bgc__isnull=False
        ).values_list("integrated_bgc_id", flat=True)
    )
    validated_col_set = {
        pri_id_to_row[v] for v in validated_ibgc_ids if v in pri_id_to_row
    }

    leaf_to_rows: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(pri_leaf_paths):
        if p:
            leaf_to_rows[p].append(i)
    leaf_col_sums: dict[str, np.ndarray] = {
        leaf: np.asarray(M_dom_pri[rows].sum(axis=0)).reshape(-1)
        for leaf, rows in leaf_to_rows.items()
    }

    # Build asset matrices on the primary's column space.
    M_dom_q = build_asset_domain_matrix(
        virtual_ibgcs, sources=sources, domain_accs=dom_accs
    )
    M_pair_q = build_asset_adjacency_pair_matrix(
        virtual_ibgcs, sources=sources, pair_vocab=pair_vocab
    )

    # Cast dom matrices to a common dtype for vstack.
    M_dom_full = sp.vstack([M_dom_pri.astype(M_dom_q.dtype), M_dom_q], format="csr")
    M_pair_full = sp.vstack([M_pair_pri.astype(M_pair_q.dtype), M_pair_q], format="csr")
    sim_full = compute_composite_similarity(
        M_dom_full, M_pair_full, weights=weights, prune_below=0.0,
    )
    sim_block = sim_full[n_primary:, :n_primary].tocsr()
    M_dom_q_csr = M_dom_q.tocsr()

    for q_row, vibgc in enumerate(virtual_ibgcs):
        sp_start = sim_block.indptr[q_row]
        sp_end = sim_block.indptr[q_row + 1]
        if sp_start == sp_end:
            continue
        cols = sim_block.indices[sp_start:sp_end]
        vals = sim_block.data[sp_start:sp_end]
        order = np.argsort(-vals)[:KNN_K]
        top_cols = cols[order]
        top_vals = vals[order]
        top_sum = float(top_vals.sum())
        if top_sum < MIN_TOTAL_SIMILARITY:
            continue

        weights_norm = top_vals / top_sum
        vibgc.umap_x = float((pri_coords[top_cols, 0] * weights_norm).sum())
        vibgc.umap_y = float((pri_coords[top_cols, 1] * weights_norm).sum())
        vibgc.umap_projected = True

        votes: Counter[str] = Counter()
        for col, val in zip(top_cols.tolist(), top_vals.tolist()):
            leaf = pri_leaf_paths[col]
            if leaf:
                votes[leaf] += float(val)
        if votes:
            vibgc.gene_cluster_family = votes.most_common(1)[0][0]

        # Novelty against validated primary cols inside this row's non-zeros.
        if validated_col_set:
            max_sim_validated = 0.0
            for col, val in zip(cols.tolist(), vals.tolist()):
                if col in validated_col_set and val > max_sim_validated:
                    max_sim_validated = float(val)
            vibgc.novelty_score = 1.0 - max_sim_validated

        # Domain novelty against the inherited leaf GCF.
        q_dom_start = M_dom_q_csr.indptr[q_row]
        q_dom_end = M_dom_q_csr.indptr[q_row + 1]
        n_dom = int(q_dom_end - q_dom_start)
        if n_dom and vibgc.gene_cluster_family:
            col_sums_L = leaf_col_sums.get(vibgc.gene_cluster_family)
            if col_sums_L is not None:
                domain_cols = M_dom_q_csr.indices[q_dom_start:q_dom_end]
                n_unique = int((col_sums_L[domain_cols] == 0).sum())
                vibgc.domain_novelty = n_unique / n_dom


# ── Step 4: materialise Redis payloads ─────────────────────────────────────


def _ordered_architecture(vibgc: VirtualIbgc, sources: tuple[str, ...]) -> list[dict]:
    """Pooled positional architecture across all member BGCs of the virtual iBGC.

    Mirrors :func:`discovery.services.architecture.ibgc_architecture` but
    walks the in-memory rows.
    """
    upper_sources = tuple(s.upper() for s in sources)
    cds_start_by_id: dict[tuple[tuple[str, int, int, str], str], int] = {}
    for cds in vibgc.cds:
        cds_start_by_id[(cds.bgc_key, cds.protein_id_str)] = cds.start_position

    from discovery.services.architecture import _interpro_url

    seen: set[tuple[int, int, str]] = set()
    ordered: list[tuple[int, int, dict]] = []
    for d in vibgc.domains:
        if not d.domain_acc:
            continue
        if d.ref_db and d.ref_db.upper() not in upper_sources:
            continue
        cds_start = cds_start_by_id.get((d.bgc_key, d.cds_protein_id))
        if cds_start is None:
            continue
        ipr_acc = (d.interpro_entry_acc or "").strip()
        if ipr_acc:
            projected = {
                "domain_acc": ipr_acc,
                "domain_name": d.interpro_entry_description or d.domain_name,
                "ref_db": "InterPro",
                "url": _interpro_url(ipr_acc),
                "start": 0,
                "end": 0,
                "score": None,
                "go_slim": go_slim_for_terms(d.go_terms),
            }
        else:
            projected = {
                "domain_acc": d.domain_acc,
                "domain_name": d.domain_name,
                "ref_db": d.ref_db,
                "url": d.url,
                "start": 0,
                "end": 0,
                "score": None,
                "go_slim": go_slim_for_terms(d.go_terms),
            }
        key = (cds_start, d.start_position, projected["domain_acc"])
        if key in seen:
            continue
        seen.add(key)
        ordered.append((cds_start, d.start_position, projected))
    ordered.sort(key=lambda t: (t[0], t[1], t[2]["domain_acc"]))
    return [t[2] for t in ordered]


def _roster_row(vibgc: VirtualIbgc) -> dict[str, Any]:
    return {
        "id": vibgc.neg_id,
        "label": vibgc.label,
        "classification_path": vibgc.gene_cluster_family,
        "size_kb": vibgc.size_kb,
        "n_source_bgcs": len(vibgc.member_bgcs),
        "source_tools": vibgc.source_tools,
        "novelty_score": vibgc.novelty_score,
        "domain_novelty": vibgc.domain_novelty,
        "is_partial": vibgc.is_partial,
        "is_validated": vibgc.is_validated,
        "is_type_strain": vibgc.is_type_strain,
        "umap_projected": vibgc.umap_projected,
        "umap_x": vibgc.umap_x,
        "umap_y": vibgc.umap_y,
        "parent_assembly_id": None,
        "parent_assembly_accession": vibgc.assembly_accession,
        "organism_name": vibgc.organism_name,
        "contig_accession": vibgc.contig_accession,
        "similarity_score": None,
        "best_hit_protein_id": None,
        "best_pident": None,
        "best_qcoverage": None,
        "is_asset": True,
    }


def _ibgc_detail(vibgc: VirtualIbgc, sources: tuple[str, ...]) -> dict[str, Any]:
    member_items = [
        {
            "id": -idx - 1,  # synthetic, scoped to this asset iBGC
            "accession": f"{vibgc.label}.{idx + 1}",
            "detector_name": m.detector_name,
            "is_partial": m.is_partial,
            "is_validated": m.is_validated,
            "size_kb": m.size_kb,
        }
        for idx, m in enumerate(vibgc.member_bgcs)
    ]
    parent_assembly = {
        "assembly_id": None,
        "accession": vibgc.assembly_accession,
        "organism_name": vibgc.organism_name,
        "source_name": None,
        "is_type_strain": vibgc.is_type_strain,
        "url": "",
    }
    nps: list[dict[str, Any]] = []
    for np_obj in vibgc.natural_products:
        nps.append(
            {
                "id": 0,
                "name": np_obj.name,
                "smiles": np_obj.smiles,
                "smiles_svg": "",
                "structure_thumbnail": np_obj.structure_svg_base64,
                "np_class_path": np_obj.np_class_path,
            }
        )

    # Aggregate per-CDS chemont rows into a flat tree (no ontology lookup in
    # the asset path — keep it light; the frontend renders leaves directly).
    chemont_aggregate: dict[str, dict[str, Any]] = {}
    for c in vibgc.cds_chemont:
        cur = chemont_aggregate.get(c.chemont_id)
        if cur is None:
            chemont_aggregate[c.chemont_id] = {
                "chemont_id": c.chemont_id,
                "name": c.chemont_name,
                "depth": 0,
                "probability": c.probability,
                "n_cds": 1,
                "children": [],
            }
        else:
            cur["probability"] = max(cur["probability"] or 0.0, c.probability)
            cur["n_cds"] += 1
    chemont_tree = list(chemont_aggregate.values())

    return {
        "id": vibgc.neg_id,
        "label": vibgc.label,
        "classification_path": vibgc.gene_cluster_family,
        "size_kb": vibgc.size_kb,
        "start_position": vibgc.start_position,
        "end_position": vibgc.end_position,
        "contig_accession": vibgc.contig_accession,
        "source_tools": vibgc.source_tools,
        "novelty_score": vibgc.novelty_score,
        "domain_novelty": vibgc.domain_novelty,
        "is_partial": vibgc.is_partial,
        "is_validated": vibgc.is_validated,
        "is_type_strain": vibgc.is_type_strain,
        "umap_projected": vibgc.umap_projected,
        "umap_x": vibgc.umap_x,
        "umap_y": vibgc.umap_y,
        "parent_assembly": parent_assembly,
        # Use the iBGC's own negative id as the representative — the region
        # endpoint resolves it back through asset_cache.read_region(token, id).
        "representative_bgc_id": vibgc.neg_id if vibgc.member_bgcs else None,
        "member_bgcs": member_items,
        "domain_architecture": _ordered_architecture(vibgc, sources),
        "natural_products": nps,
        "chemont_tree": chemont_tree,
    }


def _region_payload(vibgc: VirtualIbgc) -> dict[str, Any]:
    """Region payload matching ``BgcRegionOut`` for the asset iBGC.

    Coordinates are translated to be relative to the iBGC interval, like the
    persistent region view does for IntegratedBgc rows.
    """
    window_start = vibgc.start_position
    region_length = vibgc.end_position - vibgc.start_position

    cds_list = []
    domain_list: list[dict[str, Any]] = []
    domains_by_cds_pid: dict[tuple[tuple[str, int, int, str], str], list[AssetDomain]] = defaultdict(list)
    for d in vibgc.domains:
        domains_by_cds_pid[(d.bgc_key, d.cds_protein_id)].append(d)
    chemont_by_cds: dict[tuple[tuple[str, int, int, str], str], AssetCdsChemOnt] = {
        (c.bgc_key, c.protein_id_str): c for c in vibgc.cds_chemont
    }

    from discovery.services.architecture import collapse_to_interpro_rows

    for cds in vibgc.cds:
        sequence = ""
        if cds.sequence_zlib_b64:
            try:
                import zlib

                sequence = zlib.decompress(base64.b64decode(cds.sequence_zlib_b64)).decode(
                    "ascii", errors="replace"
                )
            except Exception:  # noqa: BLE001
                sequence = ""

        cds_domains = domains_by_cds_pid.get((cds.bgc_key, cds.protein_id_str), [])
        interpro = collapse_to_interpro_rows(
            cds_domains, slim_for=lambda d: go_slim_for_terms(d.go_terms)
        )

        pfam = []
        for d in cds_domains:
            slim = go_slim_for_terms(d.go_terms)
            pfam.append(
                {
                    "accession": d.domain_acc,
                    "description": d.domain_description or d.domain_name,
                    "go_slim": slim,
                    "envelope_start": d.start_position,
                    "envelope_end": d.end_position,
                    "e_value": str(d.score) if d.score is not None else None,
                    "url": d.url,
                }
            )
            # RegionPlot.tsx builds the per-CDS dominant-slim colouring map
            # off `domain_list` only — it never reads cds_list[*].pfam. AA→NT
            # conversion mirrors _build_bgc_region_data so the strand handling
            # stays consistent with the persistent path.
            if cds.strand >= 0:
                dom_nt_start = cds.start_position + d.start_position * 3
                dom_nt_end = cds.start_position + d.end_position * 3
            else:
                dom_nt_start = cds.end_position - d.end_position * 3
                dom_nt_end = cds.end_position - d.start_position * 3
            domain_list.append(
                {
                    "accession": d.domain_acc,
                    "description": d.domain_description or d.domain_name or "",
                    "start": max(0, dom_nt_start - window_start),
                    "end": max(0, dom_nt_end - window_start),
                    "strand": cds.strand,
                    "score": d.score,
                    "go_slim": list(slim),
                    "parent_cds_id": cds.protein_id_str,
                    "url": d.url or "",
                }
            )

        chemont_hit = chemont_by_cds.get((cds.bgc_key, cds.protein_id_str))
        cds_list.append(
            {
                "protein_id": cds.protein_id_str,
                "start": cds.start_position - window_start,
                "end": cds.end_position - window_start,
                "strand": cds.strand,
                "protein_length": cds.protein_length,
                "gene_caller": cds.gene_caller,
                "cluster_representative": cds.cluster_representative or None,
                "cluster_representative_url": None,
                "sequence": sequence,
                "pfam": pfam,
                "interpro": interpro,
                "chemont_id": chemont_hit.chemont_id if chemont_hit else None,
                "chemont_name": chemont_hit.chemont_name if chemont_hit else None,
                "chemont_probability": (
                    chemont_hit.probability if chemont_hit else None
                ),
                "chemont_weight": chemont_hit.weight if chemont_hit else None,
            }
        )

    cluster_list = [
        {
            "accession": f"{vibgc.label}.{idx + 1}",
            "start": m.start_position - window_start,
            "end": m.end_position - window_start,
            "source": m.detector_name,
            "bgc_classes": (
                [m.classification_path.split(".", 1)[0]]
                if m.classification_path
                else []
            ),
        }
        for idx, m in enumerate(vibgc.member_bgcs)
    ]

    return {
        "region_length": region_length,
        "window_start": 0,
        "window_end": region_length,
        "cds_list": cds_list,
        "domain_list": domain_list,
        "cluster_list": cluster_list,
    }


# ── Top-level entry point ──────────────────────────────────────────────────


def project_asset(token: str, data: AssetData, *, task_id: str = "") -> dict[str, Any]:
    """Run the full asset projection and materialise Redis payloads.

    Returns a summary dict (mirrored into the task status payload).
    """
    virtual_ibgcs = build_virtual_ibgcs(data)
    if not virtual_ibgcs:
        raise ValueError("No iBGCs could be built from the upload")

    run = _latest_clustering_run()
    if run is not None:
        _project_against_run(virtual_ibgcs, run)
    else:
        log.warning(
            "project_asset: no ClusteringRun present — iBGCs persisted unprojected"
        )

    sources = tuple(run.domain_sources) if run else DEFAULT_DOMAIN_SOURCES

    roster_rows = [_roster_row(v) for v in virtual_ibgcs]
    asset_cache.write_ibgc_list(token, roster_rows)

    # Flat per-iBGC-deduped domain-hit list for the report builder. Mirrors
    # the SQL ``domain_pairs`` set semantics at services/report.py:154.
    domain_hits: list[dict[str, Any]] = []
    for vibgc in virtual_ibgcs:
        seen_accs: set[str] = set()
        for d in vibgc.domains:
            if not d.domain_acc or d.domain_acc in seen_accs:
                continue
            seen_accs.add(d.domain_acc)
            domain_hits.append({
                "ibgc_id": vibgc.neg_id,
                "domain_acc": d.domain_acc,
                "domain_name": d.domain_name,
                "domain_description": d.domain_description or d.domain_name,
                "go_slim": go_slim_for_terms(d.go_terms),
            })
    asset_cache.write_domain_hits(token, domain_hits)

    for vibgc in virtual_ibgcs:
        detail = _ibgc_detail(vibgc, sources)
        region = _region_payload(vibgc)
        architecture = [d["domain_acc"] for d in detail["domain_architecture"]]
        asset_cache.write_ibgc_detail(token, vibgc.neg_id, detail)
        asset_cache.write_region(token, vibgc.neg_id, region)
        asset_cache.write_architecture(token, vibgc.neg_id, architecture)

    first = virtual_ibgcs[0]
    summary = {
        "token": token,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "n_ibgcs": len(virtual_ibgcs),
        "n_bgcs": sum(len(v.member_bgcs) for v in virtual_ibgcs),
        "assembly_accession": first.assembly_accession,
        "organism": first.organism_name,
        "source_label": ", ".join(sorted({b.detector_name for v in virtual_ibgcs for b in v.member_bgcs})),
        "clustering_run_id": run.id if run is not None else None,
        "projected": run is not None,
        "n_projected": sum(1 for v in virtual_ibgcs if v.umap_projected),
    }
    asset_cache.write_manifest(token, summary)
    asset_cache.mark_success(token, task_id=task_id, summary=summary)
    log.info(
        "project_asset: token=%s n_ibgcs=%d projected=%d",
        token,
        len(virtual_ibgcs),
        summary["n_projected"],
    )
    return summary
