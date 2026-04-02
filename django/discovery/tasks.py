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
