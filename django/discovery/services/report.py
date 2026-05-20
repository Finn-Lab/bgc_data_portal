"""Shortlist Report payload builder.

Stateless: given a list of iBGC ids, return a ready-to-render dict with all
the panels the Report Page needs (iBGC rows, domain composition, GCF
distribution, score distributions, completeness pie, BGC class pie, length
histogram, predictor distribution, assembly roster, assembly stats).

The endpoint layer caches the payload in Redis keyed by ``sha256(sorted ids)``
so reloading the report page is cheap. Nothing is persisted to the DB.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from discovery.models import (
    BgcDomain,
    DashboardAssembly,
    DashboardBgc,
    DashboardContig,
    IntegratedBGC,
)

log = logging.getLogger(__name__)

REPORT_TTL_SECONDS = 86_400  # 24h Redis TTL
MAX_SHORTLIST = 100

# Tier thresholds for the Domain Composition stacked-bar.
CORE_FRACTION = 0.8
VARIABLE_FRACTION = 0.4

# Length-histogram buckets (kb).
LENGTH_BUCKETS: list[tuple[float, float, str]] = [
    (0, 10, "<10 kb"),
    (10, 20, "10–20"),
    (20, 40, "20–40"),
    (40, 80, "40–80"),
    (80, 160, "80–160"),
    (160, float("inf"), "≥160"),
]

# Score-histogram sampling cap (avoid blowing the payload up for huge lists).
SCORE_SAMPLE_CAP = 500


def _taxonomy_phylum(taxonomy_path: Optional[str]) -> Optional[str]:
    if not taxonomy_path:
        return None
    parts = taxonomy_path.split(".")
    return parts[1] if len(parts) >= 2 else parts[0]


def _is_partial(ibgc: IntegratedBGC) -> bool:
    return bool(ibgc.umap_projected) or ibgc.classification_run_id is None


def build_report_payload(
    ibgc_ids: list[int],
    *,
    extra_ibgc_rows: Optional[list[dict]] = None,
    extra_domain_rows: Optional[list[dict]] = None,
) -> dict:
    """Assemble the complete report payload for a shortlist of iBGC ids.

    ``extra_ibgc_rows`` are already-shaped asset roster rows (from
    ``asset:{token}:ibgcs`` in Redis); ``extra_domain_rows`` is the asset's
    flat per-iBGC-deduped domain-hit list (from
    ``asset:{token}:domain_hits``). Together they feed every panel that
    derives from per-iBGC or per-domain rows: score distributions,
    completeness pie, length histogram, BGC-class pie, predictor pie,
    domain composition (and the GO slim matrix), GCF distribution, and
    the source distribution (asset iBGCs all collapse into a single
    'Assets' bucket).

    Taxonomy sunburst + assembly stats stay persistent-only — assets have
    no ``DashboardAssembly`` row to join against.

    Returns a JSON-serialisable dict matching the ``ReportPayload`` schema
    (minus ``token`` which the endpoint sets).
    """
    # Negative ids belong to assets; keep them out of ORM filters but let
    # the asset rows feed every per-iBGC/per-domain aggregate below.
    db_ibgc_ids = sorted({nid for nid in ibgc_ids if nid >= 0})
    extra_ibgc_rows = list(extra_ibgc_rows or [])
    extra_domain_rows = list(extra_domain_rows or [])
    ibgcs = list(
        IntegratedBGC.objects.select_related("contig").filter(id__in=db_ibgc_ids)
    )
    n_ibgcs = len(ibgcs) + len(extra_ibgc_rows)
    now = timezone.now()
    expires_at = now + timedelta(seconds=REPORT_TTL_SECONDS)

    if n_ibgcs == 0:
        return _empty_payload(now, expires_at)

    # ── Member BGCs grouped by iBGC (single sweep) ─────────────────────────
    members = list(
        DashboardBgc.objects
        .filter(integrated_bgc_id__in=db_ibgc_ids)
        .select_related("assembly", "assembly__source", "contig", "detector")
    )
    members_by_ibgc: dict[int, list[DashboardBgc]] = defaultdict(list)
    for m in members:
        members_by_ibgc[m.integrated_bgc_id].append(m)

    # ── iBGC rows + parent-assembly collection ─────────────────────────────
    assembly_ids: set[int] = set()
    ibgc_rows: list[dict] = []
    for ibgc in ibgcs:
        mems = members_by_ibgc.get(ibgc.id, [])
        is_validated = any(m.is_validated for m in mems)
        # ORed across all member assemblies — matches dashboard semantics.
        is_type_strain = any(
            m.assembly is not None and m.assembly.is_type_strain for m in mems
        )
        first_asm = mems[0].assembly if mems else None
        if first_asm:
            assembly_ids.add(first_asm.id)
        contig = ibgc.contig
        ibgc_rows.append({
            "id": ibgc.id,
            "label": f"iBGC-{ibgc.id}",
            "classification_path": ibgc.gene_cluster_family or "",
            "size_kb": round((ibgc.end_position - ibgc.start_position) / 1000.0, 3),
            "novelty_score": ibgc.novelty_score,
            "domain_novelty": ibgc.domain_novelty,
            "n_source_bgcs": len(mems),
            "source_tools": list(ibgc.source_tools or []),
            "is_partial": _is_partial(ibgc),
            "is_validated": is_validated,
            "is_type_strain": is_type_strain,
            "parent_assembly_accession": first_asm.assembly_accession if first_asm else None,
            "parent_assembly_id": first_asm.id if first_asm else None,
            "organism_name": first_asm.organism_name if first_asm else None,
            "biome_path": first_asm.biome_path if first_asm else "",
            "taxonomy_phylum": _taxonomy_phylum(contig.taxonomy_path if contig else None),
            "contig_accession": contig.accession if contig else None,
        })

    # ── Domain composition (core / variable / rare per acc) ───────────────
    domain_to_ibgcs: dict[str, set[int]] = defaultdict(set)
    domain_name_lookup: dict[str, str] = {}
    domain_desc_lookup: dict[str, str] = {}
    domain_goslim_lookup: dict[str, str] = {}
    domain_pairs = (
        BgcDomain.objects
        .filter(bgc__integrated_bgc_id__in=db_ibgc_ids)
        .values_list(
            "bgc__integrated_bgc_id",
            "domain_acc",
            "domain_name",
            "domain_description",
            "go_slim",
        )
    )
    # BgcDomain.go_slim is a list of slim term names; the heatmap categories
    # are keyed by a single string, so collapse to the first term (sorted)
    # for now. Multi-slim heatmap explosion can be revisited later.
    def _slim_str(value) -> str:
        if isinstance(value, list):
            return value[0] if value else ""
        return value or ""

    for nid, acc, name, desc, slim in domain_pairs:
        if not acc:
            continue
        domain_to_ibgcs[acc].add(nid)
        if name and acc not in domain_name_lookup:
            domain_name_lookup[acc] = name
        if desc and acc not in domain_desc_lookup:
            domain_desc_lookup[acc] = desc
        slim_str = _slim_str(slim)
        if slim_str and acc not in domain_goslim_lookup:
            domain_goslim_lookup[acc] = slim_str

    # Fold in asset domain hits (negative iBGC ids); the set keyed by acc
    # treats them identically to persisted iBGCs for the tier denominator.
    for r in extra_domain_rows:
        acc = r.get("domain_acc")
        if not acc:
            continue
        nid = int(r["ibgc_id"])
        domain_to_ibgcs[acc].add(nid)
        name = r.get("domain_name") or ""
        if name and acc not in domain_name_lookup:
            domain_name_lookup[acc] = name
        desc = r.get("domain_description") or ""
        if desc and acc not in domain_desc_lookup:
            domain_desc_lookup[acc] = desc
        slim = _slim_str(r.get("go_slim"))
        if slim and acc not in domain_goslim_lookup:
            domain_goslim_lookup[acc] = slim

    composition_rows: list[dict] = []
    core_count = variable_count = rare_count = 0
    # Per (go_slim, tier) bucket of distinct domains for the heatmap.
    matrix_buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    # Long-format rows for the analyst JSON export (one per iBGC × domain hit).
    domains_long: list[dict] = []
    NO_GOSLIM = "No GO slim"
    for acc, hit_ibgcs in sorted(
        domain_to_ibgcs.items(), key=lambda kv: (-len(kv[1]), kv[0])
    ):
        c = len(hit_ibgcs)
        frac = c / n_ibgcs
        if frac >= CORE_FRACTION:
            tier = "core"
            core_count += 1
        elif frac >= VARIABLE_FRACTION:
            tier = "variable"
            variable_count += 1
        else:
            tier = "rare"
            rare_count += 1
        name = domain_name_lookup.get(acc, "")
        desc = domain_desc_lookup.get(acc, "")
        slim = domain_goslim_lookup.get(acc, "") or NO_GOSLIM
        composition_rows.append({
            "domain_acc": acc,
            "domain_name": name,
            "domain_description": desc,
            "go_slim": slim,
            "ibgc_count": c,
            "fraction": round(frac, 4),
            "tier": tier,
        })
        matrix_buckets[(slim, tier)].append({
            "domain_acc": acc,
            "domain_name": name,
            "domain_description": desc,
        })
        for nid in sorted(hit_ibgcs):
            domains_long.append({
                "ibgc_id": nid,
                "domain_acc": acc,
                "domain_name": name,
                "domain_description": desc,
                "go_slim": slim,
                "tier": tier,
                "occurs_in_n_ibgcs": c,
                "fraction": round(frac, 4),
            })
    domain_composition = {
        "core_count": core_count,
        "variable_count": variable_count,
        "rare_count": rare_count,
        "total_unique": len(composition_rows),
        "rows": composition_rows,
    }

    # ── GO slim × tier matrix (for the Domain composition heatmap) ────────
    # Categories: every go_slim value with ≥1 domain in the shortlist, plus
    # "No GO slim" if any unmapped domains. Sorted by total descending so the
    # heaviest categories sit on the left of the heatmap.
    category_totals: dict[str, int] = defaultdict(int)
    for (slim, _tier), domains in matrix_buckets.items():
        category_totals[slim] += len(domains)
    categories = sorted(
        category_totals.keys(),
        key=lambda c: (-category_totals[c], c),
    )
    tiers = ["core", "variable", "rare"]
    cells = []
    for cat in categories:
        for tier in tiers:
            doms = matrix_buckets.get((cat, tier), [])
            cells.append({
                "category": cat,
                "tier": tier,
                "count": len(doms),
                "domains": doms,
            })
    domain_goslim_matrix = {
        "categories": categories,
        "tiers": tiers,
        "cells": cells,
    }

    # ── GCF distribution ──────────────────────────────────────────────────
    gcf_counts: dict[str, int] = defaultdict(int)
    for ibgc in ibgcs:
        gcf_counts[ibgc.gene_cluster_family or "(unclassified)"] += 1
    # Asset iBGCs were KNN-projected onto the latest ClusteringRun in
    # services/asset_upload/project.py:_project_against_run — their
    # classification_path is the inherited leaf GCF.
    for r in extra_ibgc_rows:
        gcf_counts[r.get("classification_path") or "(unclassified)"] += 1
    gcf_distribution = sorted(
        [
            {
                "classification_path": p,
                "ibgc_count": c,
                "fraction": round(c / n_ibgcs, 4),
            }
            for p, c in gcf_counts.items()
        ],
        key=lambda r: (-r["ibgc_count"], r["classification_path"]),
    )

    # ── Score distributions (capped sample for histogram rendering) ───────
    novelty_vals = [
        float(n.novelty_score) for n in ibgcs if n.novelty_score is not None
    ]
    for r in extra_ibgc_rows:
        if r.get("novelty_score") is not None:
            novelty_vals.append(float(r["novelty_score"]))
    novelty_vals = novelty_vals[:SCORE_SAMPLE_CAP]
    dn_vals = [
        float(n.domain_novelty) for n in ibgcs if n.domain_novelty is not None
    ]
    for r in extra_ibgc_rows:
        if r.get("domain_novelty") is not None:
            dn_vals.append(float(r["domain_novelty"]))
    dn_vals = dn_vals[:SCORE_SAMPLE_CAP]
    score_distributions = [
        {"label": "Novelty", "values": novelty_vals},
        {"label": "Domain Novelty", "values": dn_vals},
    ]

    # ── Completeness pie ──────────────────────────────────────────────────
    projected_n = sum(1 for n in ibgcs if n.umap_projected)
    unclustered_n = sum(
        1 for n in ibgcs
        if not n.umap_projected and n.classification_run_id is None
    )
    # Asset rows: projected when umap_projected, else unclustered.
    for r in extra_ibgc_rows:
        if r.get("umap_projected"):
            projected_n += 1
        else:
            unclustered_n += 1
    primary_n = n_ibgcs - projected_n - unclustered_n
    completeness_pie = [
        {"name": "Clustered (primary)", "count": primary_n},
        {"name": "Projected partial", "count": projected_n},
        {"name": "Unclustered", "count": unclustered_n},
    ]

    # ── BGC class pie ─────────────────────────────────────────────────────
    # Mirrors the ``bgc_class`` filter (api.py): an iBGC matches a class when
    # any of its source DashboardBgcs has ``classification_path`` starting
    # with that class. An iBGC with source members in multiple classes counts
    # once per distinct class.
    class_counts: dict[str, int] = defaultdict(int)
    for ibgc in ibgcs:
        mems = members_by_ibgc.get(ibgc.id, [])
        classes: set[str] = set()
        for m in mems:
            cp = (m.classification_path or "").strip()
            if cp:
                classes.add(cp.split(".")[0])
        if not classes:
            classes.add("(unclassified)")
        for head in classes:
            class_counts[head] += 1
    for r in extra_ibgc_rows:
        cp = (r.get("classification_path") or "").strip()
        head = cp.split(".")[0] if cp else "(unclassified)"
        class_counts[head] += 1
    bgc_class_pie = sorted(
        [{"name": k, "count": v} for k, v in class_counts.items()],
        key=lambda r: (-r["count"], r["name"]),
    )

    # ── Length histogram ──────────────────────────────────────────────────
    bucket_counts = [0] * len(LENGTH_BUCKETS)
    for ibgc in ibgcs:
        kb = (ibgc.end_position - ibgc.start_position) / 1000.0
        for i, (lo, hi, _) in enumerate(LENGTH_BUCKETS):
            if lo <= kb < hi:
                bucket_counts[i] += 1
                break
    for r in extra_ibgc_rows:
        kb = float(r.get("size_kb") or 0.0)
        for i, (lo, hi, _) in enumerate(LENGTH_BUCKETS):
            if lo <= kb < hi:
                bucket_counts[i] += 1
                break
    length_histogram = [
        {"label": lbl, "count": c}
        for (_, _, lbl), c in zip(LENGTH_BUCKETS, bucket_counts)
    ]

    # ── Predictor distribution ────────────────────────────────────────────
    predictor_counts: dict[str, int] = defaultdict(int)
    for ibgc in ibgcs:
        for tool in (ibgc.source_tools or []):
            predictor_counts[tool] += 1
    for r in extra_ibgc_rows:
        for tool in (r.get("source_tools") or []):
            predictor_counts[tool] += 1
    predictor_distribution = sorted(
        [{"name": k, "count": v} for k, v in predictor_counts.items()],
        key=lambda r: (-r["count"], r["name"]),
    )

    # ── Source distribution (iBGCs per source collection) ──────────────────
    # For each iBGC, collect the set of source-collection names across its
    # source DashboardBgcs (deduped per iBGC so an iBGC with two members from
    # the same collection counts once for that collection).
    source_counts: dict[str, int] = defaultdict(int)
    for ibgc in ibgcs:
        names: set[str] = set()
        for m in members_by_ibgc.get(ibgc.id, []):
            src = getattr(m.assembly, "source", None) if m.assembly else None
            if src and src.name:
                names.add(src.name)
        for name in names:
            source_counts[name] += 1
    # Asset iBGCs have no AssemblySource row; collapse them into one bucket.
    if extra_ibgc_rows:
        source_counts["Assets"] += len(extra_ibgc_rows)
    source_distribution = sorted(
        [{"name": k, "count": v} for k, v in source_counts.items()],
        key=lambda r: (-r["count"], r["name"]),
    )

    # ── Assembly roster + stats ───────────────────────────────────────────
    assemblies = list(
        DashboardAssembly.objects
        .filter(id__in=assembly_ids)
        .select_related("source")
    )
    contig_taxonomy_lookup: dict[int, str] = {}
    for c in DashboardContig.objects.filter(
        assembly_id__in=assembly_ids
    ).values("assembly_id", "taxonomy_path"):
        if c["taxonomy_path"] and c["assembly_id"] not in contig_taxonomy_lookup:
            contig_taxonomy_lookup[c["assembly_id"]] = c["taxonomy_path"]

    ibgcs_per_assembly: dict[int, int] = defaultdict(int)
    for r in ibgc_rows:
        if r["parent_assembly_id"]:
            ibgcs_per_assembly[r["parent_assembly_id"]] += 1

    assembly_rows = []
    for asm in assemblies:
        tx = contig_taxonomy_lookup.get(asm.id, "")
        assembly_rows.append({
            "id": asm.id,
            "accession": asm.assembly_accession,
            "organism_name": asm.organism_name,
            "source_name": asm.source.name if asm.source else None,
            "biome_path": asm.biome_path,
            "taxonomy_path": tx,
            "taxonomy_phylum": _taxonomy_phylum(tx),
            "assembly_size_mb": asm.assembly_size_mb,
            "total_bgcs_in_assembly": asm.bgc_count,
            "ibgcs_in_shortlist": ibgcs_per_assembly.get(asm.id, 0),
            "is_type_strain": asm.is_type_strain,
        })

    # Reuse existing assembly-stats helper for taxonomy / biome / source.
    # Stats are decorative; on failure we log and continue with an empty dict
    # so the rest of the report still renders.
    from discovery.services.stats import compute_assembly_stats
    try:
        assembly_stats = compute_assembly_stats(
            DashboardAssembly.objects.filter(id__in=assembly_ids)
        )
    except Exception:  # noqa: BLE001
        log.exception(
            "compute_assembly_stats failed for shortlist; "
            "returning empty assembly_stats"
        )
        assembly_stats = {}

    # ── iBGC-derived taxonomy sunburst ─────────────────────────────────────
    # One count per iBGC (using its contig's taxonomy_path), so the sunburst
    # reflects shortlist hits — not the size of the parent assembly.
    from discovery.services.stats import build_taxonomy_sunburst_from_paths
    ibgc_taxonomy_paths = [
        n.contig.taxonomy_path for n in ibgcs
        if n.contig and n.contig.taxonomy_path
    ]
    taxonomy_sunburst = build_taxonomy_sunburst_from_paths(ibgc_taxonomy_paths)

    # Prepend ephemeral asset rows so they appear at the top of the report's
    # iBGC roster (matches the dashboard's ordering).
    if extra_ibgc_rows:
        ibgc_rows = list(extra_ibgc_rows) + ibgc_rows

    return {
        "generated_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "n_ibgcs": n_ibgcs,
        "n_assemblies": len(assembly_rows),
        "ibgc_rows": ibgc_rows,
        "domain_composition": domain_composition,
        "gcf_distribution": gcf_distribution,
        "score_distributions": score_distributions,
        "completeness_pie": completeness_pie,
        "bgc_class_pie": bgc_class_pie,
        "length_histogram": length_histogram,
        "predictor_distribution": predictor_distribution,
        "source_distribution": source_distribution,
        "assembly_rows": assembly_rows,
        "assembly_stats": assembly_stats,
        "taxonomy_sunburst": taxonomy_sunburst,
        "domain_goslim_matrix": domain_goslim_matrix,
        # Internal: long-form per-iBGC × domain rows for the analyst export.
        # Not part of the ``ReportPayload`` schema (stripped before responding).
        "_domains_long": domains_long,
    }


ANALYST_SCHEMA_VERSION = "1"


def build_report_analyst_export(token: str, payload: dict) -> dict:
    """Reshape a cached Report payload into an analyst-friendly JSON.

    Two-layer structure: a ``metadata`` block plus tidy long-form arrays
    suitable for pandas/R consumption. Pure function over the cached
    payload — no DB queries — so it stays reload-safe within the TTL.
    """
    return {
        "metadata": {
            "schema_version": ANALYST_SCHEMA_VERSION,
            "token": token,
            "generated_at": payload.get("generated_at"),
            "expires_at": payload.get("expires_at"),
            "n_ibgcs": payload.get("n_ibgcs", 0),
            "n_assemblies": payload.get("n_assemblies", 0),
        },
        "ibgcs": payload.get("ibgc_rows", []),
        "assemblies": payload.get("assembly_rows", []),
        "domains_long": payload.get("_domains_long", []),
        "bgc_class_counts": payload.get("bgc_class_pie", []),
        "completeness_counts": payload.get("completeness_pie", []),
        "length_histogram": payload.get("length_histogram", []),
        "predictor_distribution": payload.get("predictor_distribution", []),
        "source_distribution": payload.get("source_distribution", []),
        "gcf_distribution": payload.get("gcf_distribution", []),
        "score_distributions": payload.get("score_distributions", []),
        "taxonomy_sunburst": payload.get("taxonomy_sunburst", []),
    }


def _empty_payload(now, expires_at) -> dict:
    return {
        "generated_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "n_ibgcs": 0,
        "n_assemblies": 0,
        "ibgc_rows": [],
        "domain_composition": {
            "core_count": 0, "variable_count": 0, "rare_count": 0,
            "total_unique": 0, "rows": [],
        },
        "gcf_distribution": [],
        "score_distributions": [
            {"label": "Novelty", "values": []},
            {"label": "Domain Novelty", "values": []},
        ],
        "completeness_pie": [],
        "bgc_class_pie": [],
        "length_histogram": [],
        "predictor_distribution": [],
        "source_distribution": [],
        "assembly_rows": [],
        "assembly_stats": {},
        "taxonomy_sunburst": [],
        "domain_goslim_matrix": {"categories": [], "tiers": [], "cells": []},
        "_domains_long": [],
    }
