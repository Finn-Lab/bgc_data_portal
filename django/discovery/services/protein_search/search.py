"""phmmer query against the on-disk protein DB."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from pyhmmer.easel import Alphabet, DigitalSequenceBlock, TextSequence
from pyhmmer.hmmer import phmmer

from .index import protein_search_index

log = logging.getLogger(__name__)

QUERY_NAME = b"query"

# Permissive E-value passed to phmmer itself. We do not filter on e-value;
# the real cutoffs are applied below via bitscore / %identity / query coverage.
_PHMMER_E = 10.0


@dataclass(slots=True, frozen=True)
class ProteinHitMetrics:
    """Per-target-protein metrics extracted from a phmmer hit.

    ``pident`` and ``qcoverage`` are expressed as percentages in [0, 100].
    They are aggregated across **all domains of the hit** — coverage is the
    fraction of the query covered by the union of non-overlapping domain
    envelopes; identity is the identity-count-weighted average across those
    same domain alignments.
    """

    bitscore: float
    pident: float
    qcoverage: float


def _union_length(intervals: list[tuple[int, int]]) -> int:
    """Length of the union of inclusive 1-indexed integer intervals."""
    if not intervals:
        return 0
    sorted_iv = sorted(intervals)
    total = 0
    cur_lo, cur_hi = sorted_iv[0]
    for lo, hi in sorted_iv[1:]:
        if lo > cur_hi + 1:
            total += cur_hi - cur_lo + 1
            cur_lo, cur_hi = lo, hi
        else:
            if hi > cur_hi:
                cur_hi = hi
    total += cur_hi - cur_lo + 1
    return total


def _compute_hit_metrics(hit, query_len: int) -> Optional[ProteinHitMetrics]:
    """Aggregate domain-level alignment stats into a single hit-level metrics
    record. Returns ``None`` if the hit has no usable alignments.
    """
    intervals: list[tuple[int, int]] = []
    sum_identities = 0
    sum_aligned = 0
    for dom in hit.domains:
        aln = dom.alignment
        if aln is None:
            continue
        # For phmmer, the query is internally wrapped as an HMM, so
        # hmm_from / hmm_to are the query coordinates (1-indexed, inclusive).
        hmm_from = int(aln.hmm_from)
        hmm_to = int(aln.hmm_to)
        if hmm_to < hmm_from:
            continue
        intervals.append((hmm_from, hmm_to))

        identity_str = aln.identity_sequence or ""
        # pyhmmer convention for the midline:
        #   letter  → identical residue
        #   '+'     → conservative substitution (similar, but not identical)
        #   ' '     → mismatch / gap
        sum_identities += sum(1 for c in identity_str if c.isalpha())
        sum_aligned += len(identity_str)

    if not intervals or query_len <= 0 or sum_aligned == 0:
        return None

    pident = (sum_identities / sum_aligned) * 100.0
    qcoverage = (_union_length(intervals) / query_len) * 100.0
    return ProteinHitMetrics(
        bitscore=float(hit.score),
        pident=pident,
        qcoverage=qcoverage,
    )


def phmmer_search(
    sequence: str,
    *,
    min_bitscore: float = 30.0,
    min_pident: float = 70.0,
    min_qcov: float = 70.0,
    cpus: int = 1,
    block: Optional[DigitalSequenceBlock] = None,
) -> dict[str, ProteinHitMetrics]:
    """Run phmmer with ``sequence`` against the on-disk protein DB and return
    per-target metrics for hits that pass all three thresholds.

    Parameters
    ----------
    sequence
        Amino-acid query (single protein).
    min_bitscore
        Drop hits whose full-sequence bit score is below this. Default 30
        (HMMER's conventional weak-significance cut).
    min_pident
        Drop hits whose aggregate percent identity (across all aligned
        domains) is below this. 0–100.
    min_qcov
        Drop hits whose query coverage (union of domain envelopes / query
        length) is below this. 0–100.
    cpus
        Worker threads. Default 1 to match ``--concurrency=1``.
    block
        Override the target block (used by tests). When omitted, loads the
        shared worker-local index.

    Returns
    -------
    ``{sha256: ProteinHitMetrics}`` — for each matched protein, the metrics
    of the hit. If a target appears more than once (it should not, since the
    FASTA is deduplicated by sha256), the higher-bitscore record wins.
    """
    seq = sequence.strip().upper()
    query_len = len(seq)
    alphabet = Alphabet.amino()
    target_block = block if block is not None else protein_search_index.get_block()

    query_seq = TextSequence(name=QUERY_NAME, sequence=seq).digitize(alphabet)

    results: dict[str, ProteinHitMetrics] = {}
    # phmmer yields one TopHits per query; we always pass a single query so this
    # loop iterates exactly once.
    for top_hits in phmmer(
        (query_seq,),
        target_block,
        cpus=cpus,
        E=_PHMMER_E,
    ):
        for hit in top_hits:
            if float(hit.score) < min_bitscore:
                continue
            metrics = _compute_hit_metrics(hit, query_len)
            if metrics is None:
                continue
            if metrics.pident < min_pident or metrics.qcoverage < min_qcov:
                continue
            sha256 = hit.name.decode("ascii")
            existing = results.get(sha256)
            if existing is None or metrics.bitscore > existing.bitscore:
                results[sha256] = metrics

    log.info(
        "phmmer_search: query_len=%d min_bitscore=%g min_pident=%g min_qcov=%g hits=%d",
        query_len, min_bitscore, min_pident, min_qcov, len(results),
    )
    return results
