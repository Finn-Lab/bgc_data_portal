"""Stable-forever accession ledger for cBGCs and iBGCs.

Accessions are minted once and never reassigned. Identity is the
``(entity_type, contig_accession, start_pos, end_pos)`` tuple — the same
entity reproduced after a rebuild reuses its accession. When an entity
disappears between rebuilds, the registry row stays (tombstoned: its
``current_*`` FK is NULL); the resolve endpoint returns 410 for it.

cBGC accessions: ``MGYB-XXXXXX`` (6 Crockford base32 chars after the dash)
iBGC accessions: ``MGYB-XXXXXX-YY`` (cBGC accession + 2-char per-cBGC suffix)

Crockford base32 omits ``I``, ``L``, ``O``, ``U`` from the alphabet to avoid
copy-paste ambiguity. 32^6 ≈ 1.07B cBGCs; 32^2 = 1024 iBGCs per cBGC.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from django.db import IntegrityError, connection, transaction

from discovery.models import (
    AccessionAlias,
    AccessionEntityType,
    AccessionRegistry,
    ConsensusBgc,
    IntegratedBgc,
)

logger = logging.getLogger(__name__)

# Crockford base32: no I/L/O/U; case-insensitive on input, uppercase on output.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CBGC_WIDTH = 6
_IBGC_SUFFIX_WIDTH = 2


def encode_crockford(value: int, width: int) -> str:
    """Encode a non-negative integer into a fixed-width Crockford base32 string."""
    if value < 0:
        raise ValueError("Crockford encoding requires a non-negative integer")
    if value >= 32 ** width:
        raise ValueError(
            f"value {value} exceeds {width}-char Crockford base32 capacity"
        )
    chars = []
    for _ in range(width):
        value, rem = divmod(value, 32)
        chars.append(_CROCKFORD[rem])
    return "".join(reversed(chars))


# ── Sequences (created by the squashed migration) ───────────────────────────


_CBGC_SEQUENCE = "discovery_cbgc_accession_seq"


def _ensure_sequences_exist() -> None:
    """Idempotently create the Postgres sequence backing cBGC accession minting.

    Called lazily from ``_next_cbgc_index`` so this module works on dev DBs
    that haven't run the bootstrap RunSQL yet. Cheap: the CREATE is a no-op
    once the sequence exists.
    """
    with connection.cursor() as cur:
        cur.execute(f"CREATE SEQUENCE IF NOT EXISTS {_CBGC_SEQUENCE} AS bigint;")


def _next_cbgc_index() -> int:
    _ensure_sequences_exist()
    with connection.cursor() as cur:
        cur.execute(f"SELECT nextval(%s)", [_CBGC_SEQUENCE])
        return int(cur.fetchone()[0])


def _next_ibgc_suffix_index(cbgc_id: int) -> int:
    """Return the next per-cBGC iBGC suffix index (0-based).

    Counts existing iBGCs in the cBGC. Safe under contention because the
    exclusion constraint on ``(cbgc, bgc_range)`` rejects overlapping
    inserts; a colliding insert by another worker will fail before we
    commit and the caller retries.
    """
    return IntegratedBgc.objects.filter(cbgc_id=cbgc_id).count()


# ── Mint / lookup ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CbgcAccession:
    accession: str
    registry_row: AccessionRegistry
    minted: bool  # True = freshly created this call, False = reused


def lookup_or_mint_cbgc(
    *,
    contig_accession: str,
    start_pos: int,
    end_pos: int,
    cbgc: Optional[ConsensusBgc] = None,
) -> CbgcAccession:
    """Return the stable accession for a cBGC at these coordinates.

    If a registry row already exists for ``(cbgc, contig_accession, start_pos,
    end_pos)``, returns it (and points ``current_cbgc`` at ``cbgc`` if
    provided). Otherwise mints a new ``MGYB-XXXXXX`` accession.
    """
    existing = AccessionRegistry.objects.filter(
        entity_type=AccessionEntityType.CBGC,
        contig_accession=contig_accession,
        start_pos=start_pos,
        end_pos=end_pos,
    ).first()
    if existing is not None:
        if cbgc is not None and existing.current_cbgc_id != cbgc.id:
            existing.current_cbgc = cbgc
            existing.save(update_fields=["current_cbgc", "last_seen_at"])
        return CbgcAccession(existing.accession, existing, minted=False)

    # Mint. Retry once on the rare race where another worker minted the same
    # identity tuple between our SELECT and INSERT.
    for _ in range(2):
        idx = _next_cbgc_index()
        accession = f"MGYB-{encode_crockford(idx, _CBGC_WIDTH)}"
        try:
            with transaction.atomic():
                row = AccessionRegistry.objects.create(
                    accession=accession,
                    entity_type=AccessionEntityType.CBGC,
                    contig_accession=contig_accession,
                    start_pos=start_pos,
                    end_pos=end_pos,
                    current_cbgc=cbgc,
                )
            return CbgcAccession(accession, row, minted=True)
        except IntegrityError:
            existing = AccessionRegistry.objects.filter(
                entity_type=AccessionEntityType.CBGC,
                contig_accession=contig_accession,
                start_pos=start_pos,
                end_pos=end_pos,
            ).first()
            if existing is not None:
                if cbgc is not None and existing.current_cbgc_id != cbgc.id:
                    existing.current_cbgc = cbgc
                    existing.save(update_fields=["current_cbgc", "last_seen_at"])
                return CbgcAccession(existing.accession, existing, minted=False)
            # Fell through: the IntegrityError was on the accession PK
            # (someone else burned our nextval). Bump and try again.
    raise RuntimeError(
        f"Failed to mint cBGC accession after retry for contig={contig_accession!r}"
    )


@dataclass(frozen=True)
class IbgcAccession:
    accession: str
    registry_row: AccessionRegistry
    minted: bool


def lookup_or_mint_ibgc(
    *,
    cbgc: ConsensusBgc,
    contig_accession: str,
    start_pos: int,
    end_pos: int,
    ibgc: Optional[IntegratedBgc] = None,
) -> IbgcAccession:
    """Return the stable accession for an iBGC at these coordinates.

    The accession is ``{cbgc.accession}-{YY}`` where ``YY`` is a per-cBGC
    Crockford base32 suffix. Stable across rebuilds via registry lookup.
    """
    existing = AccessionRegistry.objects.filter(
        entity_type=AccessionEntityType.IBGC,
        contig_accession=contig_accession,
        start_pos=start_pos,
        end_pos=end_pos,
    ).first()
    if existing is not None:
        if ibgc is not None and existing.current_ibgc_id != ibgc.id:
            existing.current_ibgc = ibgc
            existing.save(update_fields=["current_ibgc", "last_seen_at"])
        return IbgcAccession(existing.accession, existing, minted=False)

    for _ in range(64):
        suffix_idx = _next_ibgc_suffix_index(cbgc.id)
        if suffix_idx >= 32 ** _IBGC_SUFFIX_WIDTH:
            raise RuntimeError(
                f"cBGC {cbgc.accession} has exhausted its 1024-iBGC suffix space"
            )
        accession = f"{cbgc.accession}-{encode_crockford(suffix_idx, _IBGC_SUFFIX_WIDTH)}"
        try:
            with transaction.atomic():
                row = AccessionRegistry.objects.create(
                    accession=accession,
                    entity_type=AccessionEntityType.IBGC,
                    contig_accession=contig_accession,
                    start_pos=start_pos,
                    end_pos=end_pos,
                    current_ibgc=ibgc,
                )
            return IbgcAccession(accession, row, minted=True)
        except IntegrityError:
            existing = AccessionRegistry.objects.filter(
                entity_type=AccessionEntityType.IBGC,
                contig_accession=contig_accession,
                start_pos=start_pos,
                end_pos=end_pos,
            ).first()
            if existing is not None:
                if ibgc is not None and existing.current_ibgc_id != ibgc.id:
                    existing.current_ibgc = ibgc
                    existing.save(update_fields=["current_ibgc", "last_seen_at"])
                return IbgcAccession(existing.accession, existing, minted=False)
            # PK collision (this suffix index was burned by another iBGC
            # for the same cBGC). Try the next index.
    raise RuntimeError(
        f"Failed to mint iBGC accession for cBGC {cbgc.accession} after 64 retries"
    )


# ── Tombstoning ─────────────────────────────────────────────────────────────


def tombstone_unused(entity_type: AccessionEntityType) -> int:
    """NULL ``current_*`` on every registry row whose entity no longer exists.

    Called after a rebuild to mark accessions whose underlying cBGC / iBGC
    is gone. The resolve endpoint surfaces these as HTTP 410.
    """
    if entity_type == AccessionEntityType.CBGC:
        live_ids = set(ConsensusBgc.objects.values_list("id", flat=True))
        qs = (
            AccessionRegistry.objects
            .filter(entity_type=entity_type, current_cbgc__isnull=False)
            .exclude(current_cbgc_id__in=live_ids)
        )
        return qs.update(current_cbgc=None)

    if entity_type == AccessionEntityType.IBGC:
        live_ids = set(IntegratedBgc.objects.values_list("id", flat=True))
        qs = (
            AccessionRegistry.objects
            .filter(entity_type=entity_type, current_ibgc__isnull=False)
            .exclude(current_ibgc_id__in=live_ids)
        )
        return qs.update(current_ibgc=None)

    raise ValueError(f"Unknown entity_type: {entity_type!r}")


# ── Resolve ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolveResult:
    accession: str        # canonical (registry PK)
    kind: str             # "cbgc" | "ibgc"
    current_id: Optional[int]
    tombstoned: bool
    alias_of: Optional[str]  # set when the input was an alias


def resolve(accession: str) -> Optional[ResolveResult]:
    """Look up an accession (canonical or alias). Returns ``None`` if unknown.

    Aliases (e.g. pre-refactor ``MGYB00000001`` style) resolve to their
    current registry row. Tombstoned accessions return a result with
    ``tombstoned=True`` and ``current_id=None``.
    """
    alias_of: Optional[str] = None

    row = AccessionRegistry.objects.filter(accession=accession).first()
    if row is None:
        alias = AccessionAlias.objects.select_related("registry").filter(
            alias_accession=accession,
        ).first()
        if alias is None:
            return None
        row = alias.registry
        alias_of = alias.alias_accession

    if row.entity_type == AccessionEntityType.CBGC:
        current_id = row.current_cbgc_id
    else:
        current_id = row.current_ibgc_id

    return ResolveResult(
        accession=row.accession,
        kind=row.entity_type,
        current_id=current_id,
        tombstoned=current_id is None,
        alias_of=alias_of,
    )
