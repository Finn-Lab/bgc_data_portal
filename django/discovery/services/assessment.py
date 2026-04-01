"""Asset evaluation service — core computation for genome and BGC assessment.

Computes percentile ranks, redundancy matrices, novelty decomposition,
domain differentials, and GCF context for the Asset Evaluation dashboard mode.
"""

from __future__ import annotations

import numpy as np
from django.db.models import Avg, Count, F, Q
from pgvector.django import CosineDistance

from discovery.models import (
    BgcScore,
    GCF,
    GCFMembership,
    GenomeScore,
    MibigReference,
)
from discovery.services.scoring import compute_composite_priority
from mgnify_bgcs.models import (
    Assembly,
    Bgc,
    Cds,
    Domain,
    ProteinDomain,
)


# Score dimensions for genome percentile analysis
GENOME_SCORE_DIMENSIONS = [
    ("bgc_diversity_score", "Diversity"),
    ("bgc_novelty_score", "Novelty"),
    ("bgc_density", "Density"),
]

# Threshold for GCF novelty — if distance to nearest GCF representative
# exceeds this, the BGC is considered a novel singleton.
GCF_NOVELTY_DISTANCE_THRESHOLD = 0.7


def compute_genome_assessment(assembly_id: int, weights: dict) -> dict:
    """Produce a full genome assessment report.

    Parameters
    ----------
    assembly_id : int
        Primary key of the Assembly to assess.
    weights : dict
        User-selected weights for composite priority (w_diversity, w_novelty, w_density).

    Returns
    -------
    dict
        Serializable assessment payload matching GenomeAssessmentResponse.
    """
    assembly = Assembly.objects.get(pk=assembly_id)
    genome_score = GenomeScore.objects.get(assembly=assembly)

    # ── Percentile ranks ─────────────────────────────────────────────────
    total_all = GenomeScore.objects.count()
    total_ts = GenomeScore.objects.filter(assembly__is_type_strain=True).count()

    percentile_ranks = []
    for dim, label in GENOME_SCORE_DIMENSIONS:
        value = getattr(genome_score, dim)
        count_all = GenomeScore.objects.filter(**{f"{dim}__lte": value}).count()
        count_ts = GenomeScore.objects.filter(
            assembly__is_type_strain=True, **{f"{dim}__lte": value}
        ).count()
        percentile_ranks.append(
            {
                "dimension": dim,
                "label": label,
                "value": round(value, 4),
                "percentile_all": round(count_all / max(total_all, 1) * 100, 1),
                "percentile_type_strain": round(count_ts / max(total_ts, 1) * 100, 1),
            }
        )

    # ── Composite score and DB rank ──────────────────────────────────────
    score_map = {
        "bgc_diversity_score": genome_score.bgc_diversity_score,
        "bgc_novelty_score": genome_score.bgc_novelty_score,
        "bgc_density": genome_score.bgc_density,
    }
    weight_map = {
        "bgc_diversity_score": weights.get("w_diversity", 0.30),
        "bgc_novelty_score": weights.get("w_novelty", 0.45),
        "bgc_density": weights.get("w_density", 0.25),
    }
    composite = compute_composite_priority(score_map, weight_map)

    # Count genomes with higher composite score
    # We compute on the fly since weights are user-tunable
    all_scores = GenomeScore.objects.values_list(
        "bgc_diversity_score", "bgc_novelty_score", "bgc_density"
    )
    higher_count = 0
    for div, nov, den in all_scores:
        other_composite = compute_composite_priority(
            {"bgc_diversity_score": div, "bgc_novelty_score": nov, "bgc_density": den},
            weight_map,
        )
        if other_composite > composite:
            higher_count += 1
    db_rank = higher_count + 1
    db_total = total_all

    # ── BGC novelty breakdown ────────────────────────────────────────────
    bgcs = Bgc.objects.filter(
        contig__assembly=assembly, bgc_score__isnull=False
    ).select_related("bgc_score")

    bgc_novelty_breakdown = []
    for bgc in bgcs:
        score = getattr(bgc, "bgc_score", None)
        bgc_novelty_breakdown.append(
            {
                "bgc_id": bgc.id,
                "accession": bgc.accession,
                "classification_l1": score.classification_l1 if score else "",
                "novelty_vs_mibig": round(score.nearest_mibig_distance or 0.0, 4)
                if score
                else 0.0,
                "novelty_vs_db": round(score.novelty_score, 4) if score else 0.0,
                "domain_novelty": round(score.domain_novelty, 4) if score else 0.0,
            }
        )
    bgc_novelty_breakdown.sort(key=lambda x: x["novelty_vs_db"], reverse=True)

    # ── Redundancy matrix ────────────────────────────────────────────────
    redundancy_matrix = []
    for bgc in bgcs:
        score = getattr(bgc, "bgc_score", None)
        membership = getattr(bgc, "gcf_membership", None)
        if membership is None:
            try:
                membership = GCFMembership.objects.get(bgc=bgc)
            except GCFMembership.DoesNotExist:
                membership = None

        if membership is None:
            redundancy_matrix.append(
                {
                    "bgc_id": bgc.id,
                    "accession": bgc.accession,
                    "classification_l1": score.classification_l1 if score else "",
                    "gcf_family_id": None,
                    "gcf_member_count": 0,
                    "gcf_has_mibig": False,
                    "gcf_has_type_strain": False,
                    "status": "novel_gcf",
                }
            )
            continue

        gcf = membership.gcf
        has_mibig = bool(gcf.mibig_accession)
        # Check if any co-member's assembly is a type strain
        has_type_strain = GCFMembership.objects.filter(
            gcf=gcf
        ).exclude(bgc=bgc).filter(
            bgc__contig__assembly__is_type_strain=True
        ).exists()

        if has_type_strain:
            status = "known_gcf_type_strain"
        else:
            status = "known_gcf_no_type_strain"

        redundancy_matrix.append(
            {
                "bgc_id": bgc.id,
                "accession": bgc.accession,
                "classification_l1": score.classification_l1 if score else "",
                "gcf_family_id": gcf.family_id,
                "gcf_member_count": gcf.member_count,
                "gcf_has_mibig": has_mibig,
                "gcf_has_type_strain": has_type_strain,
                "status": status,
            }
        )

    # ── Chemical space ───────────────────────────────────────────────────
    # Compute sparse threshold: 75th percentile of all DB BGC nearest-MIBiG distances
    all_mibig_dists = list(
        BgcScore.objects.filter(
            nearest_mibig_distance__isnull=False
        ).values_list("nearest_mibig_distance", flat=True)[:10_000]
    )
    sparse_threshold = float(np.percentile(all_mibig_dists, 75)) if all_mibig_dists else 0.5

    chemical_space_points = []
    for bgc in bgcs:
        meta = bgc.metadata or {}
        score = getattr(bgc, "bgc_score", None)
        mibig_dist = score.nearest_mibig_distance if score else None
        chemical_space_points.append(
            {
                "bgc_id": bgc.id,
                "accession": bgc.accession,
                "umap_x": meta.get("umap_x_coord", 0.0),
                "umap_y": meta.get("umap_y_coord", 0.0),
                "classification_l1": score.classification_l1 if score else "",
                "nearest_mibig_distance": round(mibig_dist or 0.0, 4),
                "is_sparse": (mibig_dist or 0.0) > sparse_threshold,
            }
        )

    # MIBiG reference points for the UMAP
    mibig_points = list(
        MibigReference.objects.values("accession", "compound_name", "bgc_class", "umap_x", "umap_y")
    )

    sparse_count = sum(1 for p in chemical_space_points if p["is_sparse"])
    sparse_fraction = sparse_count / max(len(chemical_space_points), 1)
    mean_mibig_dist = (
        np.mean([p["nearest_mibig_distance"] for p in chemical_space_points])
        if chemical_space_points
        else 0.0
    )

    # ── Radar reference data ─────────────────────────────────────────────
    radar_references = []
    for dim, label in GENOME_SCORE_DIMENSIONS:
        agg = GenomeScore.objects.aggregate(
            db_mean=Avg(dim),
        )
        # Sample values for p90
        vals = list(
            GenomeScore.objects.values_list(dim, flat=True)[:10_000]
        )
        db_p90 = float(np.percentile(vals, 90)) if vals else 0.0
        radar_references.append(
            {
                "dimension": dim,
                "label": label,
                "db_mean": round(agg["db_mean"] or 0.0, 4),
                "db_p90": round(db_p90, 4),
            }
        )

    return {
        "assembly_id": assembly.id,
        "accession": assembly.accession,
        "organism_name": assembly.organism_name,
        "is_type_strain": assembly.is_type_strain,
        "percentile_ranks": percentile_ranks,
        "db_rank": db_rank,
        "db_total": db_total,
        "composite_score": round(composite, 4),
        "bgc_novelty_breakdown": bgc_novelty_breakdown,
        "redundancy_matrix": redundancy_matrix,
        "chemical_space_points": chemical_space_points,
        "mibig_reference_points": mibig_points,
        "mean_nearest_mibig_distance": round(float(mean_mibig_dist), 4),
        "sparse_fraction": round(sparse_fraction, 4),
        "radar_references": radar_references,
    }


def compute_bgc_assessment(bgc_id: int) -> dict:
    """Produce a full BGC assessment report.

    Parameters
    ----------
    bgc_id : int
        Primary key of the Bgc to assess.

    Returns
    -------
    dict
        Serializable assessment payload matching BgcAssessmentResponse.
    """
    bgc = Bgc.objects.select_related("contig__assembly").get(pk=bgc_id)
    score = BgcScore.objects.filter(bgc=bgc).first()

    classification_l1 = score.classification_l1 if score else ""
    classification_l2 = score.classification_l2 if score else None

    # ── GCF placement ────────────────────────────────────────────────────
    membership = GCFMembership.objects.filter(bgc=bgc).select_related("gcf").first()
    gcf_context = None
    distance_to_rep = None
    is_novel_singleton = False

    if membership:
        gcf = membership.gcf
        distance_to_rep = membership.distance_to_representative
        gcf_context = _build_gcf_context(gcf, bgc)
    elif bgc.embedding is not None:
        # Try nearest-neighbor GCF placement
        gcf, distance_to_rep = _find_nearest_gcf(bgc)
        if gcf and distance_to_rep <= GCF_NOVELTY_DISTANCE_THRESHOLD:
            gcf_context = _build_gcf_context(gcf, bgc)
        else:
            is_novel_singleton = True
            distance_to_rep = None
    else:
        is_novel_singleton = True

    # ── Domain differential ──────────────────────────────────────────────
    domain_differential = []
    submitted_domains = _get_bgc_domains(bgc)
    submitted_domain_accs = {d["domain_acc"] for d in submitted_domains}

    if gcf_context:
        gcf_domain_freq = {
            d["domain_acc"]: d for d in gcf_context["domain_frequency"]
        }

        # Classify domains that are in the submitted BGC
        for acc in submitted_domain_accs:
            freq_item = gcf_domain_freq.get(acc)
            freq = freq_item["frequency"] if freq_item else 0.0
            name = freq_item["domain_name"] if freq_item else _get_domain_name(acc)
            if freq >= 0.8:
                category = "core"
            elif freq < 0.5:
                category = "variable"
            else:
                category = "core"  # between 0.5 and 0.8 — still relatively common
            domain_differential.append(
                {
                    "domain_acc": acc,
                    "domain_name": name,
                    "in_submitted": True,
                    "gcf_frequency": round(freq, 4),
                    "category": category,
                }
            )

        # Absent domains (in GCF consensus but not in submitted BGC)
        for acc, freq_item in gcf_domain_freq.items():
            if acc not in submitted_domain_accs and freq_item["frequency"] > 0.5:
                domain_differential.append(
                    {
                        "domain_acc": acc,
                        "domain_name": freq_item["domain_name"],
                        "in_submitted": False,
                        "gcf_frequency": round(freq_item["frequency"], 4),
                        "category": "absent",
                    }
                )

    # ── Novelty decomposition ────────────────────────────────────────────
    novelty = _compute_novelty_decomposition(bgc, score, submitted_domain_accs)

    # ── Chemical space ───────────────────────────────────────────────────
    meta = bgc.metadata or {}
    submitted_point = {
        "bgc_id": bgc.id,
        "accession": bgc.accession,
        "umap_x": meta.get("umap_x_coord", 0.0),
        "umap_y": meta.get("umap_y_coord", 0.0),
        "classification_l1": classification_l1,
        "nearest_mibig_distance": round((score.nearest_mibig_distance or 0.0) if score else 0.0, 4),
        "is_sparse": False,
    }

    nearest_neighbors = _find_nearest_neighbors(bgc, k=20)
    mibig_points = list(
        MibigReference.objects.values("accession", "compound_name", "bgc_class", "umap_x", "umap_y")
    )

    # ── Domain architecture for comparison ───────────────────────────────
    nearest_mibig_accession = score.nearest_mibig_accession if score else None
    nearest_mibig_bgc_id = None
    if nearest_mibig_accession:
        mibig_ref = MibigReference.objects.filter(
            accession=nearest_mibig_accession
        ).select_related("bgc").first()
        if mibig_ref and mibig_ref.bgc_id:
            nearest_mibig_bgc_id = mibig_ref.bgc_id

    return {
        "bgc_id": bgc.id,
        "accession": bgc.accession,
        "classification_l1": classification_l1,
        "classification_l2": classification_l2,
        "gcf_context": gcf_context,
        "distance_to_gcf_representative": round(distance_to_rep, 4) if distance_to_rep is not None else None,
        "is_novel_singleton": is_novel_singleton,
        "domain_differential": domain_differential,
        "novelty": novelty,
        "submitted_point": submitted_point,
        "nearest_neighbors": nearest_neighbors,
        "mibig_reference_points": mibig_points,
        "submitted_domains": submitted_domains,
        "nearest_mibig_accession": nearest_mibig_accession,
        "nearest_mibig_bgc_id": nearest_mibig_bgc_id,
    }


def find_similar_genomes(assembly_id: int, k: int = 10) -> list[int]:
    """Find the K most similar genomes by mean BGC embedding distance.

    Returns a list of Assembly IDs.
    """
    assembly = Assembly.objects.get(pk=assembly_id)
    bgcs = Bgc.objects.filter(
        contig__assembly=assembly, is_aggregated_region=True, embedding__isnull=False
    )
    embeddings = [bgc.embedding for bgc in bgcs]
    if not embeddings:
        return []

    # Mean embedding for the genome
    mean_embedding = np.mean(embeddings, axis=0).tolist()

    # Find nearest BGCs in other genomes
    nearest_bgcs = (
        Bgc.objects.filter(is_aggregated_region=True, embedding__isnull=False)
        .exclude(contig__assembly=assembly)
        .annotate(distance=CosineDistance("embedding", mean_embedding))
        .order_by("distance")[:k * 5]  # over-fetch to get diverse genomes
    )

    # Deduplicate by assembly
    seen_assemblies = set()
    result = []
    for bgc in nearest_bgcs.select_related("contig__assembly"):
        aid = bgc.contig.assembly_id
        if aid and aid not in seen_assemblies:
            seen_assemblies.add(aid)
            result.append(aid)
            if len(result) >= k:
                break

    return result


# ── Private helpers ──────────────────────────────────────────────────────────


def _build_gcf_context(gcf: GCF, exclude_bgc: Bgc) -> dict:
    """Build the GCF context panel data."""
    memberships = GCFMembership.objects.filter(gcf=gcf).select_related(
        "bgc__contig__assembly", "bgc__bgc_score"
    )

    member_points = []
    novelty_values = []
    taxonomy_counts: dict[str, int] = {}

    for m in memberships:
        mbgc = m.bgc
        meta = mbgc.metadata or {}
        asm = mbgc.contig.assembly if mbgc.contig else None
        is_ts = asm.is_type_strain if asm else False
        tax_family = asm.taxonomy_family if asm else "Unknown"

        member_points.append(
            {
                "bgc_id": mbgc.id,
                "umap_x": meta.get("umap_x_coord", 0.0),
                "umap_y": meta.get("umap_y_coord", 0.0),
                "is_type_strain": is_ts,
                "distance_to_representative": round(m.distance_to_representative, 4),
                "accession": mbgc.accession,
            }
        )

        bscore = getattr(mbgc, "bgc_score", None)
        if bscore:
            novelty_values.append(bscore.novelty_score)

        tf = tax_family or "Unknown"
        taxonomy_counts[tf] = taxonomy_counts.get(tf, 0) + 1

    # Domain frequency profile across GCF members
    member_bgc_ids = [m.bgc_id for m in memberships]
    domain_frequency = _compute_gcf_domain_frequency(member_bgc_ids)

    # MIBiG count: members whose parent assembly connects to a MIBiG ref
    mibig_count = 1 if gcf.mibig_accession else 0

    taxonomy_distribution = [
        {"taxonomy_family": k, "count": v}
        for k, v in sorted(taxonomy_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "gcf_id": gcf.id,
        "family_id": gcf.family_id,
        "member_count": gcf.member_count,
        "mibig_count": mibig_count,
        "mean_novelty": round(np.mean(novelty_values) if novelty_values else 0.0, 4),
        "known_chemistry_annotation": gcf.known_chemistry_annotation,
        "mibig_accession": gcf.mibig_accession,
        "domain_frequency": domain_frequency,
        "taxonomy_distribution": taxonomy_distribution,
        "member_points": member_points,
    }


def _compute_gcf_domain_frequency(member_bgc_ids: list[int]) -> list[dict]:
    """Compute domain frequency across GCF member BGCs.

    Returns list of {domain_acc, domain_name, frequency, category}.
    """
    if not member_bgc_ids:
        return []

    n_members = len(member_bgc_ids)

    # Count how many distinct BGCs each domain appears in
    domain_counts = (
        Domain.objects.filter(
            proteindomain__protein__cds__contig__bgcs__id__in=member_bgc_ids
        )
        .annotate(
            bgc_count=Count(
                "proteindomain__protein__cds__contig__bgcs",
                distinct=True,
                filter=Q(proteindomain__protein__cds__contig__bgcs__id__in=member_bgc_ids),
            )
        )
        .filter(bgc_count__gte=1)
        .values("acc", "name", "description", "bgc_count")
        .order_by("-bgc_count")
    )

    result = []
    for row in domain_counts:
        freq = row["bgc_count"] / n_members
        if freq >= 0.8:
            category = "core"
        elif freq >= 0.2:
            category = "variable"
        else:
            category = "rare"
        result.append(
            {
                "domain_acc": row["acc"],
                "domain_name": row["name"],
                "description": row["description"] or "",
                "frequency": round(freq, 4),
                "category": category,
            }
        )

    return result


def _get_bgc_domains(bgc: Bgc) -> list[dict]:
    """Get domain architecture for a BGC."""
    domains = (
        ProteinDomain.objects.filter(
            protein__cds__contig=bgc.contig_id,
            protein__cds__start_position__gte=bgc.start_position,
            protein__cds__end_position__lte=bgc.end_position,
        )
        .select_related("domain")
        .order_by("start_position")
    )

    return [
        {
            "domain_acc": pd.domain.acc,
            "domain_name": pd.domain.name,
            "ref_db": pd.domain.ref_db,
            "start": pd.start_position,
            "end": pd.end_position,
            "score": pd.score,
        }
        for pd in domains
    ]


def _get_domain_name(acc: str) -> str:
    """Lookup a domain name by accession."""
    try:
        return Domain.objects.get(acc=acc).name
    except Domain.DoesNotExist:
        return acc


def _find_nearest_gcf(bgc: Bgc) -> tuple[GCF | None, float | None]:
    """Find the nearest GCF by cosine distance to its representative BGC's embedding."""
    # Get all GCF representatives with embeddings
    gcf_reps = GCF.objects.filter(
        representative_bgc__embedding__isnull=False
    ).select_related("representative_bgc")

    if not gcf_reps.exists():
        return None, None

    rep_bgc_ids = [g.representative_bgc_id for g in gcf_reps if g.representative_bgc_id]
    if not rep_bgc_ids:
        return None, None

    # Find the nearest representative BGC
    nearest = (
        Bgc.objects.filter(id__in=rep_bgc_ids)
        .annotate(distance=CosineDistance("embedding", bgc.embedding))
        .order_by("distance")
        .first()
    )

    if nearest is None:
        return None, None

    gcf = GCF.objects.filter(representative_bgc=nearest).first()
    return gcf, nearest.distance


def _compute_novelty_decomposition(
    bgc: Bgc, score: BgcScore | None, submitted_domain_accs: set[str]
) -> dict:
    """Compute three-axis novelty decomposition for a BGC."""
    # Sequence novelty: 1 - similarity to nearest DB BGC
    sequence_novelty = 0.0
    if bgc.embedding is not None:
        nearest_db = (
            Bgc.objects.filter(is_aggregated_region=True, embedding__isnull=False)
            .exclude(pk=bgc.pk)
            .annotate(distance=CosineDistance("embedding", bgc.embedding))
            .order_by("distance")
            .values_list("distance", flat=True)
            .first()
        )
        if nearest_db is not None:
            sequence_novelty = min(float(nearest_db), 1.0)

    # Chemistry novelty: distance to nearest MIBiG
    chemistry_novelty = 0.0
    if score and score.nearest_mibig_distance is not None:
        chemistry_novelty = min(score.nearest_mibig_distance, 1.0)

    # Architecture novelty: fraction of domains not found in any other DB BGC
    architecture_novelty = 0.0
    if submitted_domain_accs:
        # Count domains that appear in at least one other BGC
        known_domains = set(
            Domain.objects.filter(
                acc__in=submitted_domain_accs,
                proteindomain__protein__cds__contig__bgcs__is_aggregated_region=True,
            )
            .exclude(
                proteindomain__protein__cds__contig__bgcs=bgc
            )
            .values_list("acc", flat=True)
            .distinct()
        )
        novel_count = len(submitted_domain_accs - known_domains)
        architecture_novelty = novel_count / len(submitted_domain_accs)

    return {
        "sequence_novelty": round(sequence_novelty, 4),
        "chemistry_novelty": round(chemistry_novelty, 4),
        "architecture_novelty": round(architecture_novelty, 4),
    }


def _find_nearest_neighbors(bgc: Bgc, k: int = 20) -> list[dict]:
    """Find K nearest DB BGCs and MIBiG references to a BGC."""
    neighbors: list[dict] = []

    if bgc.embedding is None:
        return neighbors

    # Nearest DB BGCs
    nearest_bgcs = (
        Bgc.objects.filter(is_aggregated_region=True, embedding__isnull=False)
        .exclude(pk=bgc.pk)
        .annotate(distance=CosineDistance("embedding", bgc.embedding))
        .order_by("distance")
        .select_related("bgc_score")[:k]
    )
    for nb in nearest_bgcs:
        meta = nb.metadata or {}
        neighbors.append(
            {
                "bgc_id": nb.id,
                "mibig_accession": None,
                "umap_x": meta.get("umap_x_coord", 0.0),
                "umap_y": meta.get("umap_y_coord", 0.0),
                "distance": round(float(nb.distance), 4),
                "label": nb.accession,
                "is_mibig": False,
            }
        )

    # Nearest MIBiG references
    nearest_mibig = (
        MibigReference.objects.filter(embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", bgc.embedding))
        .order_by("distance")[:5]
    )
    for mr in nearest_mibig:
        neighbors.append(
            {
                "bgc_id": None,
                "mibig_accession": mr.accession,
                "umap_x": mr.umap_x,
                "umap_y": mr.umap_y,
                "distance": round(float(mr.distance), 4),
                "label": f"{mr.accession} ({mr.compound_name})",
                "is_mibig": True,
            }
        )

    neighbors.sort(key=lambda x: x["distance"])
    return neighbors
