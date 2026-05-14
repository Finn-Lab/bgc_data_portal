"""Shortlist Report payload builder.

Stateless: given a list of NRB ids, return a ready-to-render dict with all
the panels the Report Page needs (NRB rows, domain composition, GCF
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
    NonRedundantBGC,
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


def _is_partial(nrb: NonRedundantBGC) -> bool:
    return bool(nrb.umap_projected) or nrb.classification_run_id is None


def build_report_payload(nrb_ids: list[int]) -> dict:
    """Assemble the complete report payload for a shortlist of NRB ids.

    Returns a JSON-serialisable dict that matches the ``ReportPayload``
    schema (minus ``token`` which the endpoint sets).
    """
    nrb_ids = sorted(set(nrb_ids))
    nrbs = list(
        NonRedundantBGC.objects.select_related("contig").filter(id__in=nrb_ids)
    )
    n_nrbs = len(nrbs)
    now = timezone.now()
    expires_at = now + timedelta(seconds=REPORT_TTL_SECONDS)

    if n_nrbs == 0:
        return _empty_payload(now, expires_at)

    # ── Member BGCs grouped by NRB (single sweep) ─────────────────────────
    members = list(
        DashboardBgc.objects
        .filter(non_redundant_bgc_id__in=nrb_ids)
        .select_related("assembly", "assembly__source", "contig", "detector")
    )
    members_by_nrb: dict[int, list[DashboardBgc]] = defaultdict(list)
    for m in members:
        members_by_nrb[m.non_redundant_bgc_id].append(m)

    # ── NRB rows + parent-assembly collection ─────────────────────────────
    assembly_ids: set[int] = set()
    nrb_rows: list[dict] = []
    for nrb in nrbs:
        mems = members_by_nrb.get(nrb.id, [])
        is_validated = any(m.is_validated for m in mems)
        # ORed across all member assemblies — matches dashboard semantics.
        is_type_strain = any(
            m.assembly is not None and m.assembly.is_type_strain for m in mems
        )
        first_asm = mems[0].assembly if mems else None
        if first_asm:
            assembly_ids.add(first_asm.id)
        contig = nrb.contig
        nrb_rows.append({
            "id": nrb.id,
            "label": f"NRB-{nrb.id}",
            "classification_path": nrb.gene_cluster_family or "",
            "size_kb": round((nrb.end_position - nrb.start_position) / 1000.0, 3),
            "novelty_score": nrb.novelty_score,
            "domain_novelty": nrb.domain_novelty,
            "n_source_bgcs": len(mems),
            "source_tools": list(nrb.source_tools or []),
            "is_partial": _is_partial(nrb),
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
    domain_to_nrbs: dict[str, set[int]] = defaultdict(set)
    domain_name_lookup: dict[str, str] = {}
    domain_desc_lookup: dict[str, str] = {}
    domain_goslim_lookup: dict[str, str] = {}
    domain_pairs = (
        BgcDomain.objects
        .filter(bgc__non_redundant_bgc_id__in=nrb_ids)
        .values_list(
            "bgc__non_redundant_bgc_id",
            "domain_acc",
            "domain_name",
            "domain_description",
            "go_slim",
        )
    )
    for nid, acc, name, desc, slim in domain_pairs:
        if not acc:
            continue
        domain_to_nrbs[acc].add(nid)
        if name and acc not in domain_name_lookup:
            domain_name_lookup[acc] = name
        if desc and acc not in domain_desc_lookup:
            domain_desc_lookup[acc] = desc
        if slim and acc not in domain_goslim_lookup:
            domain_goslim_lookup[acc] = slim

    composition_rows: list[dict] = []
    core_count = variable_count = rare_count = 0
    # Per (go_slim, tier) bucket of distinct domains for the heatmap.
    matrix_buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    # Long-format rows for the analyst JSON export (one per NRB × domain hit).
    domains_long: list[dict] = []
    NO_GOSLIM = "No GO slim"
    for acc, hit_nrbs in sorted(
        domain_to_nrbs.items(), key=lambda kv: (-len(kv[1]), kv[0])
    ):
        c = len(hit_nrbs)
        frac = c / n_nrbs
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
            "nrb_count": c,
            "fraction": round(frac, 4),
            "tier": tier,
        })
        matrix_buckets[(slim, tier)].append({
            "domain_acc": acc,
            "domain_name": name,
            "domain_description": desc,
        })
        for nid in sorted(hit_nrbs):
            domains_long.append({
                "nrb_id": nid,
                "domain_acc": acc,
                "domain_name": name,
                "domain_description": desc,
                "go_slim": slim,
                "tier": tier,
                "occurs_in_n_nrbs": c,
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
    for nrb in nrbs:
        gcf_counts[nrb.gene_cluster_family or "(unclassified)"] += 1
    gcf_distribution = sorted(
        [
            {
                "classification_path": p,
                "nrb_count": c,
                "fraction": round(c / n_nrbs, 4),
            }
            for p, c in gcf_counts.items()
        ],
        key=lambda r: (-r["nrb_count"], r["classification_path"]),
    )

    # ── Score distributions (capped sample for histogram rendering) ───────
    novelty_vals = [
        float(n.novelty_score) for n in nrbs if n.novelty_score is not None
    ][:SCORE_SAMPLE_CAP]
    dn_vals = [
        float(n.domain_novelty) for n in nrbs if n.domain_novelty is not None
    ][:SCORE_SAMPLE_CAP]
    score_distributions = [
        {"label": "Novelty", "values": novelty_vals},
        {"label": "Domain Novelty", "values": dn_vals},
    ]

    # ── Completeness pie ──────────────────────────────────────────────────
    projected_n = sum(1 for n in nrbs if n.umap_projected)
    unclustered_n = sum(
        1 for n in nrbs
        if not n.umap_projected and n.classification_run_id is None
    )
    primary_n = n_nrbs - projected_n - unclustered_n
    completeness_pie = [
        {"name": "Clustered (primary)", "count": primary_n},
        {"name": "Projected partial", "count": projected_n},
        {"name": "Unclustered", "count": unclustered_n},
    ]

    # ── BGC class pie ─────────────────────────────────────────────────────
    # Mirrors the ``bgc_class`` filter (api.py): an NRB matches a class when
    # any of its source DashboardBgcs has ``classification_path`` starting
    # with that class. An NRB with source members in multiple classes counts
    # once per distinct class.
    class_counts: dict[str, int] = defaultdict(int)
    for nrb in nrbs:
        mems = members_by_nrb.get(nrb.id, [])
        classes: set[str] = set()
        for m in mems:
            cp = (m.classification_path or "").strip()
            if cp:
                classes.add(cp.split(".")[0])
        if not classes:
            classes.add("(unclassified)")
        for head in classes:
            class_counts[head] += 1
    bgc_class_pie = sorted(
        [{"name": k, "count": v} for k, v in class_counts.items()],
        key=lambda r: (-r["count"], r["name"]),
    )

    # ── Length histogram ──────────────────────────────────────────────────
    bucket_counts = [0] * len(LENGTH_BUCKETS)
    for nrb in nrbs:
        kb = (nrb.end_position - nrb.start_position) / 1000.0
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
    for nrb in nrbs:
        for tool in (nrb.source_tools or []):
            predictor_counts[tool] += 1
    predictor_distribution = sorted(
        [{"name": k, "count": v} for k, v in predictor_counts.items()],
        key=lambda r: (-r["count"], r["name"]),
    )

    # ── Source distribution (NRBs per source collection) ──────────────────
    # For each NRB, collect the set of source-collection names across its
    # source DashboardBgcs (deduped per NRB so an NRB with two members from
    # the same collection counts once for that collection).
    source_counts: dict[str, int] = defaultdict(int)
    for nrb in nrbs:
        names: set[str] = set()
        for m in members_by_nrb.get(nrb.id, []):
            src = getattr(m.assembly, "source", None) if m.assembly else None
            if src and src.name:
                names.add(src.name)
        for name in names:
            source_counts[name] += 1
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

    nrbs_per_assembly: dict[int, int] = defaultdict(int)
    for r in nrb_rows:
        if r["parent_assembly_id"]:
            nrbs_per_assembly[r["parent_assembly_id"]] += 1

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
            "nrbs_in_shortlist": nrbs_per_assembly.get(asm.id, 0),
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

    # ── NRB-derived taxonomy sunburst ─────────────────────────────────────
    # One count per NRB (using its contig's taxonomy_path), so the sunburst
    # reflects shortlist hits — not the size of the parent assembly.
    from discovery.services.stats import build_taxonomy_sunburst_from_paths
    nrb_taxonomy_paths = [
        n.contig.taxonomy_path for n in nrbs
        if n.contig and n.contig.taxonomy_path
    ]
    taxonomy_sunburst = build_taxonomy_sunburst_from_paths(nrb_taxonomy_paths)

    return {
        "generated_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "n_nrbs": n_nrbs,
        "n_assemblies": len(assembly_rows),
        "nrb_rows": nrb_rows,
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
        # Internal: long-form per-NRB × domain rows for the analyst export.
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
            "n_nrbs": payload.get("n_nrbs", 0),
            "n_assemblies": payload.get("n_assemblies", 0),
        },
        "nrbs": payload.get("nrb_rows", []),
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
        "n_nrbs": 0,
        "n_assemblies": 0,
        "nrb_rows": [],
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
