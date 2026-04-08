"""Assessment service for uploaded (non-DB) assets.

Mirrors the computations in ``assessment.py`` but operates on in-memory
dicts (from Redis cache) instead of ORM model instances.  All reference
data (validated BGCs, GCFs, precomputed stats) is still read from the
live database.

The returned dicts match the same shape as ``AssemblyAssessmentResponse``
and ``BgcAssessmentResponse`` so the frontend can reuse existing views.
"""

from __future__ import annotations

import logging

import numpy as np
from django.db import connection
from django.db.models import Avg, Count

from discovery.models import (
    BgcDomain,
    BgcEmbedding,
    DashboardAssembly,
    DashboardBgc,
    DashboardGCF,
    PrecomputedStats,
)
from discovery.services.assessment import (
    ASSEMBLY_SCORE_DIMENSIONS,
    GCF_NOVELTY_DISTANCE_THRESHOLD,
    _build_gcf_context,
    _compute_gcf_domain_frequency,
)

log = logging.getLogger(__name__)

EMBEDDING_DIM = 1152


# ── Public API ────────────────────────────────────────────────────────────────


def compute_uploaded_bgc_assessment(data: dict) -> dict:
    """Produce a full BGC assessment report from uploaded (cached) data.

    ``data`` is the dict produced by ``upload_parser.parse_bgc_upload``.
    """
    embedding = data["embedding"]
    classification_path = data.get("classification_path", "")
    submitted_domain_accs = {d["domain_acc"] for d in data.get("domains", [])}

    # ── GCF placement ───────────────────────────────────────────────────
    gcf_context = None
    distance_to_rep = None
    is_novel_singleton = False

    gcf_family = data.get("gene_cluster_family", "")
    if gcf_family:
        gcf = DashboardGCF.objects.filter(family_id=gcf_family).first()
        if gcf:
            gcf_context = _build_gcf_context_for_uploaded(gcf)
            if gcf.representative_bgc_id:
                dist = _distance_to_bgc(embedding, gcf.representative_bgc_id)
                distance_to_rep = dist
        else:
            is_novel_singleton = True
    else:
        gcf, dist = _find_nearest_gcf_for_vector(embedding)
        if gcf and dist is not None and dist <= GCF_NOVELTY_DISTANCE_THRESHOLD:
            gcf_context = _build_gcf_context_for_uploaded(gcf)
            distance_to_rep = dist
        else:
            is_novel_singleton = True

    # ── Domain differential ─────────────────────────────────────────────
    submitted_domains = [
        {
            "domain_acc": d["domain_acc"],
            "domain_name": d.get("domain_name", ""),
            "ref_db": d.get("ref_db", ""),
            "start": 0,
            "end": 0,
            "score": None,
        }
        for d in data.get("domains", [])
    ]
    domain_differential = []

    if gcf_context:
        gcf_domain_freq = {
            d["domain_acc"]: d for d in gcf_context["domain_frequency"]
        }
        for acc in submitted_domain_accs:
            freq_item = gcf_domain_freq.get(acc)
            freq = freq_item["frequency"] if freq_item else 0.0
            name = freq_item["domain_name"] if freq_item else _get_domain_name(acc)
            category = "core" if freq >= 0.5 else "variable"
            domain_differential.append(
                {
                    "domain_acc": acc,
                    "domain_name": name,
                    "in_submitted": True,
                    "gcf_frequency": round(freq, 4),
                    "category": category,
                }
            )
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

    # ── Novelty decomposition ───────────────────────────────────────────
    novelty = _compute_uploaded_novelty(embedding, submitted_domain_accs)

    # ── Chemical space ──────────────────────────────────────────────────
    umap_x, umap_y = _compute_umap_coords_single(embedding)
    submitted_point = {
        "bgc_id": -1,
        "accession": f"uploaded_bgc_{data.get('index', 0)}",
        "umap_x": umap_x,
        "umap_y": umap_y,
        "classification_path": classification_path,
        "nearest_validated_distance": round(novelty["chemistry_novelty"], 4),
        "is_sparse": False,
    }

    nearest_neighbors = _find_nearest_neighbors_for_vector(embedding, k=20)
    validated_ref_points = list(
        DashboardBgc.objects.filter(is_validated=True).values(
            "bgc_accession", "classification_path", "umap_x", "umap_y"
        )
    )

    # ── Nearest validated BGC ───────────────────────────────────────────
    nearest_validated = _nearest_db_embeddings(embedding, k=1, filter_validated=True)
    nearest_validated_accession = None
    nearest_validated_bgc_id = None
    if nearest_validated:
        nv_bgc_id = nearest_validated[0][0]
        ref = DashboardBgc.objects.filter(pk=nv_bgc_id).values_list(
            "bgc_accession", flat=True
        ).first()
        if ref:
            nearest_validated_accession = ref
            nearest_validated_bgc_id = nv_bgc_id

    return {
        "bgc_id": -1,
        "accession": f"uploaded_bgc_{data.get('index', 0)}",
        "classification_path": classification_path,
        "gcf_context": gcf_context,
        "distance_to_gcf_representative": round(distance_to_rep, 4) if distance_to_rep is not None else None,
        "is_novel_singleton": is_novel_singleton,
        "domain_differential": domain_differential,
        "novelty": novelty,
        "submitted_point": submitted_point,
        "nearest_neighbors": nearest_neighbors,
        "validated_reference_points": validated_ref_points,
        "submitted_domains": submitted_domains,
        "nearest_validated_accession": nearest_validated_accession,
        "nearest_validated_bgc_id": nearest_validated_bgc_id,
    }


def compute_uploaded_assembly_assessment(data: dict) -> dict:
    """Produce a full assembly assessment report from uploaded (cached) data.

    ``data`` is the dict produced by ``upload_parser.parse_assembly_upload``.
    """
    bgcs = data.get("bgcs", [])
    if not bgcs:
        raise ValueError("Uploaded assembly has no BGCs")

    accession = data.get("accession", "uploaded_assembly")
    organism_name = data.get("organism_name", "")
    assembly_size_mb = data.get("assembly_size_mb")
    is_type_strain = data.get("is_type_strain", False)

    # ── Per-BGC novelty computation (embedding distance to nearest validated) ──
    bgc_details = []
    novelty_scores = []
    for bgc in bgcs:
        embedding = bgc["embedding"]
        domain_accs = {d["domain_acc"] for d in bgc.get("domains", [])}

        # Novelty vs validated
        nearest_validated = _nearest_db_embeddings(embedding, k=1, filter_validated=True)
        novelty_vs_validated = round(nearest_validated[0][1], 4) if nearest_validated else 0.0

        # Novelty vs DB (any BGC)
        nearest_any = _nearest_db_embeddings(embedding, k=1)
        novelty_vs_db = round(nearest_any[0][1], 4) if nearest_any else 0.0

        # Domain novelty
        domain_novelty = _compute_domain_novelty(domain_accs)

        novelty_scores.append(novelty_vs_validated)

        bgc_details.append({
            "bgc_id": -(bgc["index"] + 1),
            "accession": f"uploaded_bgc_{bgc['index']}",
            "classification_path": bgc.get("classification_path", ""),
            "novelty_vs_validated": novelty_vs_validated,
            "novelty_vs_db": novelty_vs_db,
            "domain_novelty": round(domain_novelty, 4),
            "is_partial": bgc.get("is_partial", False),
            "embedding": embedding,
        })
    bgc_details.sort(key=lambda x: x["novelty_vs_db"], reverse=True)

    # ── Assembly-level scores ───────────────────────────────────────────
    bgc_count = len(bgcs)
    l1_classes = set()
    for bgc in bgcs:
        cp = bgc.get("classification_path", "")
        if cp:
            l1_classes.add(cp.split(".")[0])
    l1_class_count = len(l1_classes)

    # Total known L1 classes in DB
    total_l1 = DashboardBgc.objects.exclude(
        classification_path=""
    ).values_list("classification_path", flat=True)
    db_l1_classes = {cp.split(".")[0] for cp in total_l1 if cp}
    total_known = max(len(db_l1_classes | l1_classes), 1)

    bgc_novelty_score = float(np.mean(novelty_scores)) if novelty_scores else 0.0
    bgc_diversity_score = l1_class_count / total_known
    bgc_density = bgc_count / assembly_size_mb if assembly_size_mb else 0.0

    total_all = DashboardAssembly.objects.count()
    total_ts = DashboardAssembly.objects.filter(is_type_strain=True).count()

    # ── Percentile ranks ────────────────────────────────────────────────
    score_values = {
        "bgc_diversity_score": bgc_diversity_score,
        "bgc_novelty_score": bgc_novelty_score,
        "bgc_density": bgc_density,
    }
    percentile_ranks = []
    for dim, label in ASSEMBLY_SCORE_DIMENSIONS:
        value = score_values[dim]
        count_all = DashboardAssembly.objects.filter(**{f"{dim}__lte": value}).count()
        pctl_all = count_all / max(total_all, 1) * 100
        count_ts = DashboardAssembly.objects.filter(
            is_type_strain=True, **{f"{dim}__lte": value}
        ).count()
        percentile_ranks.append({
            "dimension": dim,
            "label": label,
            "value": round(value, 4),
            "percentile_all": round(pctl_all, 1),
            "percentile_type_strain": round(count_ts / max(total_ts, 1) * 100, 1),
        })

    # ── DB rank ─────────────────────────────────────────────────────────
    higher_count = DashboardAssembly.objects.filter(
        bgc_novelty_score__gt=bgc_novelty_score
    ).count()
    db_rank = higher_count + 1

    # ── BGC novelty breakdown ───────────────────────────────────────────
    bgc_novelty_breakdown = [
        {k: v for k, v in d.items() if k != "embedding"}
        for d in bgc_details
    ]

    # ── Redundancy matrix ───────────────────────────────────────────────
    redundancy_matrix = []
    for detail in bgc_details:
        bgc_data = next(b for b in bgcs if b["index"] == -(detail["bgc_id"] + 1))
        gcf_family = bgc_data.get("gene_cluster_family", "")
        if not gcf_family:
            gcf, dist = _find_nearest_gcf_for_vector(bgc_data["embedding"])
            if gcf and dist is not None and dist <= GCF_NOVELTY_DISTANCE_THRESHOLD:
                gcf_family = gcf.family_id
            else:
                redundancy_matrix.append({
                    "bgc_id": detail["bgc_id"],
                    "accession": detail["accession"],
                    "classification_path": detail["classification_path"],
                    "gcf_family_id": None,
                    "gcf_member_count": 0,
                    "gcf_has_validated": False,
                    "gcf_has_type_strain": False,
                    "status": "novel_gcf",
                })
                continue

        gcf = DashboardGCF.objects.filter(family_id=gcf_family).first()
        if gcf is None:
            redundancy_matrix.append({
                "bgc_id": detail["bgc_id"],
                "accession": detail["accession"],
                "classification_path": detail["classification_path"],
                "gcf_family_id": gcf_family,
                "gcf_member_count": 0,
                "gcf_has_validated": False,
                "gcf_has_type_strain": False,
                "status": "novel_gcf",
            })
            continue

        has_validated = gcf.validated_count > 0
        has_type_strain = DashboardBgc.objects.filter(
            gene_cluster_family=gcf.family_id, assembly__is_type_strain=True
        ).exists()
        status = "known_gcf_type_strain" if has_type_strain else "known_gcf_no_type_strain"
        redundancy_matrix.append({
            "bgc_id": detail["bgc_id"],
            "accession": detail["accession"],
            "classification_path": detail["classification_path"],
            "gcf_family_id": gcf.family_id,
            "gcf_member_count": gcf.member_count,
            "gcf_has_validated": has_validated,
            "gcf_has_type_strain": has_type_strain,
            "status": status,
        })

    # ── Chemical space ──────────────────────────────────────────────────
    try:
        bgc_stats = PrecomputedStats.objects.get(key="bgc_global")
        sparse_threshold = bgc_stats.data.get("sparse_threshold", 0.5)
    except PrecomputedStats.DoesNotExist:
        sparse_threshold = 0.5

    chemical_space_points = []
    for detail in bgc_details:
        bgc_data = next(b for b in bgcs if b["index"] == -(detail["bgc_id"] + 1))
        ux, uy = _compute_umap_coords_single(bgc_data["embedding"])
        nvd = detail["novelty_vs_validated"]
        chemical_space_points.append({
            "bgc_id": detail["bgc_id"],
            "accession": detail["accession"],
            "umap_x": ux,
            "umap_y": uy,
            "classification_path": detail["classification_path"],
            "nearest_validated_distance": nvd,
            "is_sparse": nvd > sparse_threshold,
        })

    validated_ref_points = list(
        DashboardBgc.objects.filter(is_validated=True).values(
            "bgc_accession", "classification_path", "umap_x", "umap_y"
        )
    )

    sparse_count = sum(1 for p in chemical_space_points if p["is_sparse"])
    sparse_fraction = sparse_count / max(len(chemical_space_points), 1)
    mean_validated_dist = (
        float(np.mean([p["nearest_validated_distance"] for p in chemical_space_points]))
        if chemical_space_points
        else 0.0
    )

    # ── Radar references ────────────────────────────────────────────────
    try:
        assembly_stats = PrecomputedStats.objects.get(key="assembly_global")
        radar_references = assembly_stats.data.get("radar_references", [])
    except PrecomputedStats.DoesNotExist:
        radar_references = []
        for dim, label in ASSEMBLY_SCORE_DIMENSIONS:
            agg = DashboardAssembly.objects.aggregate(db_mean=Avg(dim))
            vals = list(
                DashboardAssembly.objects.values_list(dim, flat=True)[:10_000]
            )
            db_p90 = float(np.percentile(vals, 90)) if vals else 0.0
            radar_references.append({
                "dimension": dim,
                "label": label,
                "db_mean": round(agg["db_mean"] or 0.0, 4),
                "db_p90": round(db_p90, 4),
            })

    return {
        "assembly_id": -1,
        "accession": accession,
        "organism_name": organism_name,
        "is_type_strain": is_type_strain,
        "percentile_ranks": percentile_ranks,
        "db_rank": db_rank,
        "db_total": total_all,
        "bgc_novelty_breakdown": bgc_novelty_breakdown,
        "redundancy_matrix": redundancy_matrix,
        "chemical_space_points": chemical_space_points,
        "validated_reference_points": validated_ref_points,
        "mean_nearest_validated_distance": round(float(mean_validated_dist), 4),
        "sparse_fraction": round(sparse_fraction, 4),
        "radar_references": radar_references,
    }


# ── Private helpers ───────────────────────────────────────────────────────────


def _vec_to_sql(vector: list[float]) -> str:
    """Convert a Python list of floats to a pgvector literal string."""
    return "[" + ",".join(str(float(v)) for v in vector) + "]"


def _nearest_db_embeddings(
    vector: list[float],
    k: int = 1,
    filter_validated: bool = False,
) -> list[tuple[int, float]]:
    """Find K nearest BGC embeddings in the DB by cosine distance.

    Returns list of (bgc_id, distance) tuples ordered by distance.
    Uses raw SQL with a parameterized vector literal — the uploaded vector
    is never stored in the DB.
    """
    vec_str = _vec_to_sql(vector)

    where = ""
    if filter_validated:
        where = "WHERE be.bgc_id IN (SELECT id FROM discovery_bgc WHERE is_validated = TRUE)"

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT be.bgc_id, (be.vector <=> %s::halfvec({EMBEDDING_DIM})) AS distance
            FROM discovery_bgc_embedding be
            {where}
            ORDER BY be.vector <=> %s::halfvec({EMBEDDING_DIM})
            LIMIT %s
            """,
            [vec_str, vec_str, k],
        )
        return cursor.fetchall()


def _distance_to_bgc(vector: list[float], bgc_id: int) -> float | None:
    """Compute cosine distance between an uploaded vector and a specific DB BGC."""
    vec_str = _vec_to_sql(vector)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT (be.vector <=> %s::halfvec({EMBEDDING_DIM})) AS distance
            FROM discovery_bgc_embedding be
            WHERE be.bgc_id = %s
            """,
            [vec_str, bgc_id],
        )
        row = cursor.fetchone()
    return float(row[0]) if row else None


def _find_nearest_gcf_for_vector(
    vector: list[float],
) -> tuple[DashboardGCF | None, float | None]:
    """Find the nearest GCF by cosine distance to its representative's embedding."""
    rep_bgc_ids = list(
        DashboardGCF.objects.filter(
            representative_bgc__isnull=False
        ).values_list("representative_bgc_id", flat=True)
    )
    if not rep_bgc_ids:
        return None, None

    vec_str = _vec_to_sql(vector)
    placeholders = ",".join(["%s"] * len(rep_bgc_ids))

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT be.bgc_id, (be.vector <=> %s::halfvec({EMBEDDING_DIM})) AS distance
            FROM discovery_bgc_embedding be
            WHERE be.bgc_id IN ({placeholders})
            ORDER BY be.vector <=> %s::halfvec({EMBEDDING_DIM})
            LIMIT 1
            """,
            [vec_str] + rep_bgc_ids + [vec_str],
        )
        row = cursor.fetchone()

    if row is None:
        return None, None

    gcf = DashboardGCF.objects.filter(representative_bgc_id=row[0]).first()
    return gcf, float(row[1])


def _build_gcf_context_for_uploaded(gcf: DashboardGCF) -> dict:
    """Build GCF context panel — same as _build_gcf_context but without excluding a DB BGC."""
    members = DashboardBgc.objects.filter(
        gene_cluster_family=gcf.family_id
    ).select_related("assembly")

    member_points = []
    novelty_values = []
    taxonomy_counts: dict[str, int] = {}

    for mbgc in members:
        assembly = mbgc.assembly
        is_ts = assembly.is_type_strain if assembly else False
        tax_label = assembly.organism_name if assembly else "Unknown"

        member_points.append({
            "bgc_id": mbgc.id,
            "umap_x": mbgc.umap_x,
            "umap_y": mbgc.umap_y,
            "is_type_strain": is_ts,
            "accession": mbgc.bgc_accession,
        })
        novelty_values.append(mbgc.novelty_score)
        tf = tax_label or "Unknown"
        taxonomy_counts[tf] = taxonomy_counts.get(tf, 0) + 1

    member_bgc_ids = [m.id for m in members]
    domain_frequency = _compute_gcf_domain_frequency(member_bgc_ids)

    taxonomy_distribution = [
        {"taxonomy_label": k, "count": v}
        for k, v in sorted(taxonomy_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "gcf_id": gcf.id,
        "family_id": gcf.family_id,
        "member_count": gcf.member_count,
        "validated_count": gcf.validated_count,
        "mean_novelty": round(float(np.mean(novelty_values)) if novelty_values else 0.0, 4),
        "known_chemistry_annotation": gcf.known_chemistry_annotation or None,
        "validated_accession": gcf.validated_accession or None,
        "domain_frequency": domain_frequency,
        "taxonomy_distribution": taxonomy_distribution,
        "member_points": member_points,
    }


def _find_nearest_neighbors_for_vector(
    vector: list[float], k: int = 20
) -> list[dict]:
    """Find K nearest DB BGCs by cosine distance to an uploaded embedding."""
    results = _nearest_db_embeddings(vector, k=k)
    if not results:
        return []

    bgc_ids = [r[0] for r in results]
    distances = {r[0]: r[1] for r in results}
    db_bgcs = DashboardBgc.objects.filter(pk__in=bgc_ids)
    bgc_map = {b.id: b for b in db_bgcs}

    neighbors = []
    for bgc_id, distance in results:
        bgc = bgc_map.get(bgc_id)
        if bgc is None:
            continue
        neighbors.append({
            "bgc_id": bgc.id,
            "validated_accession": bgc.bgc_accession if bgc.is_validated else None,
            "umap_x": bgc.umap_x,
            "umap_y": bgc.umap_y,
            "distance": round(float(distance), 4),
            "label": bgc.bgc_accession,
            "is_validated": bgc.is_validated,
        })

    neighbors.sort(key=lambda x: x["distance"])
    return neighbors


def _compute_uploaded_novelty(
    embedding: list[float], submitted_domain_accs: set[str]
) -> dict:
    """Three-axis novelty decomposition for an uploaded BGC."""
    # Sequence novelty: distance to nearest DB BGC (any)
    nearest_any = _nearest_db_embeddings(embedding, k=1)
    sequence_novelty = min(float(nearest_any[0][1]), 1.0) if nearest_any else 0.0

    # Chemistry novelty: distance to nearest validated BGC
    nearest_validated = _nearest_db_embeddings(embedding, k=1, filter_validated=True)
    chemistry_novelty = min(float(nearest_validated[0][1]), 1.0) if nearest_validated else 0.0

    # Architecture novelty: fraction of uploaded domains not found in DB
    architecture_novelty = 0.0
    if submitted_domain_accs:
        known_domains = set(
            BgcDomain.objects.filter(domain_acc__in=submitted_domain_accs)
            .values_list("domain_acc", flat=True)
            .distinct()
        )
        novel_count = len(submitted_domain_accs - known_domains)
        architecture_novelty = novel_count / len(submitted_domain_accs)

    return {
        "sequence_novelty": round(sequence_novelty, 4),
        "chemistry_novelty": round(chemistry_novelty, 4),
        "architecture_novelty": round(architecture_novelty, 4),
    }


def _compute_domain_novelty(domain_accs: set[str]) -> float:
    """Fraction of domains not found in any DB BGC."""
    if not domain_accs:
        return 0.0
    known = set(
        BgcDomain.objects.filter(domain_acc__in=domain_accs)
        .values_list("domain_acc", flat=True)
        .distinct()
    )
    return len(domain_accs - known) / len(domain_accs)


def _compute_umap_coords_single(embedding: list[float]) -> tuple[float, float]:
    """Transform a single embedding through the saved UMAP model."""
    try:
        from mgnify_bgcs.models import UMAPTransform
    except ImportError:
        return 0.0, 0.0

    latest_model = UMAPTransform.objects.order_by("-created_at").first()
    if latest_model is None:
        return 0.0, 0.0

    import pickle

    try:
        umap_model = pickle.loads(latest_model.model_blob)
        arr = np.array([embedding], dtype=np.float32)
        coords = umap_model.transform(arr)
        return float(coords[0, 0]), float(coords[0, 1])
    except Exception:
        log.exception("Failed to compute UMAP coordinates for uploaded BGC")
        return 0.0, 0.0


def _get_domain_name(acc: str) -> str:
    """Lookup a domain name by accession from BgcDomain."""
    bd = BgcDomain.objects.filter(domain_acc=acc).first()
    return bd.domain_name if bd else acc
