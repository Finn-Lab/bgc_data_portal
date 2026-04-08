"""Celery tasks for the Asset Evaluation mode.

Each task dispatches to the assessment service, caches the result
in Redis with a 24-hour TTL, and follows the existing set_job_cache
/ get_job_status polling pattern.
"""

from __future__ import annotations

import logging

from celery import shared_task

from discovery.cache_utils import set_job_cache

log = logging.getLogger(__name__)

ASSESSMENT_TTL = 86_400  # 24 hours
UPLOAD_ASSESSMENT_TTL = 14_400  # 4 hours
CHEMICAL_QUERY_TTL = 3_600  # 1 hour


@shared_task(name="discovery.tasks.assess_assembly", bind=True, acks_late=True)
def assess_assembly(self, assembly_id: int) -> bool:
    """Run a full assembly assessment and cache the result."""
    task_id = self.request.id
    search_key = f"assess_assembly:{assembly_id}"

    # Mark as pending
    set_job_cache(search_key=search_key, task_id=task_id, timeout=ASSESSMENT_TTL)

    from discovery.services.assessment import compute_assembly_assessment

    result = compute_assembly_assessment(assembly_id)

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=ASSESSMENT_TTL,
    )
    log.info("Assembly assessment completed for assembly %s (task %s)", assembly_id, task_id)
    return True


@shared_task(name="discovery.tasks.assess_bgc", bind=True, acks_late=True)
def assess_bgc(self, bgc_id: int) -> bool:
    """Run a full BGC assessment and cache the result."""
    task_id = self.request.id
    search_key = f"assess_bgc:{bgc_id}"

    # Mark as pending
    set_job_cache(search_key=search_key, task_id=task_id, timeout=ASSESSMENT_TTL)

    from discovery.services.assessment import compute_bgc_assessment

    result = compute_bgc_assessment(bgc_id)

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=ASSESSMENT_TTL,
    )
    log.info("BGC assessment completed for BGC %s (task %s)", bgc_id, task_id)
    return True


@shared_task(name="discovery.tasks.assess_uploaded_bgc", bind=True, acks_late=True)
def assess_uploaded_bgc(self, upload_key: str) -> bool:
    """Run a full BGC assessment on uploaded (cached) data."""
    from django.core.cache import cache

    task_id = self.request.id
    search_key = f"assess_upload_bgc:{upload_key}"

    set_job_cache(search_key=search_key, task_id=task_id, timeout=UPLOAD_ASSESSMENT_TTL)

    uploaded_data = cache.get(upload_key)
    if not uploaded_data:
        set_job_cache(
            search_key=search_key,
            results={"error": "Upload expired — please re-upload"},
            task_id=task_id,
            timeout=UPLOAD_ASSESSMENT_TTL,
        )
        log.warning("Upload key %s expired before assessment (task %s)", upload_key, task_id)
        return False

    from discovery.services.uploaded_assessment import compute_uploaded_bgc_assessment

    result = compute_uploaded_bgc_assessment(uploaded_data)

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=UPLOAD_ASSESSMENT_TTL,
    )
    log.info("Uploaded BGC assessment completed (task %s)", task_id)
    return True


@shared_task(name="discovery.tasks.assess_uploaded_assembly", bind=True, acks_late=True)
def assess_uploaded_assembly(self, upload_key: str) -> bool:
    """Run a full assembly assessment on uploaded (cached) data."""
    from django.core.cache import cache

    task_id = self.request.id
    search_key = f"assess_upload_assembly:{upload_key}"

    set_job_cache(search_key=search_key, task_id=task_id, timeout=UPLOAD_ASSESSMENT_TTL)

    uploaded_data = cache.get(upload_key)
    if not uploaded_data:
        set_job_cache(
            search_key=search_key,
            results={"error": "Upload expired — please re-upload"},
            task_id=task_id,
            timeout=UPLOAD_ASSESSMENT_TTL,
        )
        log.warning("Upload key %s expired before assessment (task %s)", upload_key, task_id)
        return False

    from discovery.services.uploaded_assessment import compute_uploaded_assembly_assessment

    result = compute_uploaded_assembly_assessment(uploaded_data)

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=UPLOAD_ASSESSMENT_TTL,
    )
    log.info("Uploaded assembly assessment completed (task %s)", task_id)
    return True


@shared_task(name="discovery.tasks.recompute_scores", bind=True, acks_late=True)
def recompute_scores_task(self) -> bool:
    """Recompute all discovery scores (novelty, assembly, GCF, catalogs, UMAP)."""
    from discovery.services.scores import recompute_all_scores

    recompute_all_scores()
    log.info("Score recomputation complete (task %s)", self.request.id)
    return True


@shared_task(name="discovery.tasks.chemical_similarity_search", bind=True, acks_late=True)
def chemical_similarity_search(self, smiles: str, similarity_threshold: float) -> dict[int, float]:
    """Compute Tanimoto similarity of a SMILES query against all DashboardNaturalProduct records.

    Returns a dict mapping BGC id → max similarity score.
    Runs in the Celery worker where RDKit is available.
    """
    from rdkit import Chem
    from rdkit.Chem import DataStructs, rdFingerprintGenerator

    from discovery.models import DashboardNaturalProduct

    query_mol = Chem.MolFromSmiles(smiles.strip())
    if query_mol is None:
        log.warning("Invalid SMILES passed to chemical_similarity_search: %s", smiles[:50])
        return {}

    mfpgen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    query_fp = mfpgen.GetFingerprint(query_mol)

    bgc_similarities: dict[int, float] = {}
    for np_obj in DashboardNaturalProduct.objects.filter(bgc__isnull=False).only(
        "bgc_id", "smiles", "morgan_fp"
    ):
        if not np_obj.smiles:
            continue
        try:
            fp = None
            if np_obj.morgan_fp:
                raw = bytes(np_obj.morgan_fp) if isinstance(np_obj.morgan_fp, memoryview) else np_obj.morgan_fp
                fp = DataStructs.CreateFromBitString(raw.decode("ascii"))
            else:
                mol = Chem.MolFromSmiles(np_obj.smiles)
                if mol is None:
                    continue
                fp = mfpgen.GetFingerprint(mol)
            similarity = DataStructs.TanimotoSimilarity(query_fp, fp)
            if similarity >= similarity_threshold:
                existing = bgc_similarities.get(np_obj.bgc_id, 0.0)
                bgc_similarities[np_obj.bgc_id] = max(existing, similarity)
        except Exception as e:
            log.warning("Error processing NP id=%s: %s", np_obj.pk, e)
            continue

    log.info(
        "Chemical query: SMILES=%s threshold=%.2f matches=%d",
        smiles[:50], similarity_threshold, len(bgc_similarities),
    )
    return bgc_similarities


SEQUENCE_QUERY_TTL = 3_600  # 1 hour

_VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")


@shared_task(name="discovery.tasks.sequence_similarity_search", bind=True, acks_late=True)
def sequence_similarity_search(self, sequence: str, similarity_threshold: float) -> dict[int, float]:
    """Embed a protein sequence with ESM-C and find BGCs with similar proteins.

    Returns a dict mapping BGC id → max cosine similarity score.
    Runs in the Celery worker where torch + ESM are available.
    """
    import numpy as np
    from django.db import connection

    from discovery.models import DashboardCds

    # Validate
    seq = sequence.strip().upper()
    if not seq:
        log.warning("Empty sequence passed to sequence_similarity_search")
        return {}
    if len(seq) > 5000:
        log.warning("Sequence too long (%d AA), max 5000", len(seq))
        return {}
    invalid = set(seq) - _VALID_AA
    if invalid:
        log.warning("Invalid amino acid characters: %s", invalid)
        return {}

    # Embed
    from common_core.esmc_embedder import embed_sequences

    results = embed_sequences([seq])
    if not results or results[0] is None:
        log.error("ESM-C embedding failed for sequence (len=%d)", len(seq))
        return {}

    # Extract layer 29 (penultimate) → 1152-dim vector
    embedding = results[0][29].astype(np.float32)
    vec_str = "[" + ",".join(str(float(v)) for v in embedding) + "]"

    # pgvector cosine distance search
    max_distance = 1.0 - similarity_threshold
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT protein_sha256, (vector <=> %s::halfvec(1152)) AS distance
            FROM discovery_protein_embedding
            WHERE (vector <=> %s::halfvec(1152)) <= %s
            """,
            [vec_str, vec_str, max_distance],
        )
        rows = cursor.fetchall()

    if not rows:
        log.info("Sequence query: no protein matches at threshold=%.2f", similarity_threshold)
        return {}

    # Map matched protein_sha256 → BGC ids via DashboardCds
    matched_sha256s = {r[0]: 1.0 - r[1] for r in rows}  # sha256 → similarity
    cds_qs = (
        DashboardCds.objects.filter(protein_sha256__in=matched_sha256s.keys())
        .values_list("bgc_id", "protein_sha256")
    )

    bgc_similarities: dict[int, float] = {}
    for bgc_id, sha256 in cds_qs:
        sim = matched_sha256s[sha256]
        existing = bgc_similarities.get(bgc_id, 0.0)
        bgc_similarities[bgc_id] = max(existing, sim)

    log.info(
        "Sequence query: len=%d threshold=%.2f protein_matches=%d bgc_matches=%d",
        len(seq), similarity_threshold, len(rows), len(bgc_similarities),
    )
    return bgc_similarities
