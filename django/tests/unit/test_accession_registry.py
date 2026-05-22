"""Unit tests for the accession registry.

Covers:
  * Crockford base32 encoding (alphabet + width)
  * cBGC mint: fresh accession + identity-tuple reuse on re-lookup
  * iBGC mint: per-cBGC suffix sequencing + identity-tuple reuse
  * tombstone_unused: NULLs current_* for entities that no longer exist
  * resolve: canonical, alias, tombstoned, and unknown inputs
"""

from __future__ import annotations

import pytest

from discovery.models import (
    AccessionAlias,
    AccessionEntityType,
    AccessionRegistry,
    ConsensusBgc,
    IntegratedBgc,
)
from discovery.services.accession_registry import (
    encode_crockford,
    lookup_or_mint_cbgc,
    lookup_or_mint_ibgc,
    resolve,
    tombstone_unused,
)

from tests.factories.discovery_models import (
    ConsensusBgcFactory,
    DashboardContigFactory,
    IntegratedBgcFactory,
)


# ── encode_crockford ──────────────────────────────────────────────────────────


class TestEncodeCrockford:
    def test_alphabet_omits_iluo(self):
        # Walk every position to confirm I/L/O/U never appear in output.
        seen = set()
        for i in range(32 ** 2):
            s = encode_crockford(i, 2)
            seen.update(s)
        assert seen.isdisjoint({"I", "L", "O", "U"})

    def test_zero_pads(self):
        assert encode_crockford(0, 6) == "000000"
        assert encode_crockford(1, 6) == "000001"

    def test_round_trip_within_capacity(self):
        # Last index that fits in width=2 (32**2 - 1 = 1023).
        assert len(encode_crockford(1023, 2)) == 2
        assert encode_crockford(1023, 2) == "ZZ"

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            encode_crockford(-1, 2)

    def test_rejects_overflow(self):
        with pytest.raises(ValueError):
            encode_crockford(32 ** 2, 2)


# ── cBGC mint ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestLookupOrMintCbgc:
    def test_mints_fresh_accession_with_mgyb_prefix(self):
        contig = DashboardContigFactory()
        cbgc = ConsensusBgc.objects.create(
            contig=contig,
            bgc_range=(1000, 11_000),
            accession="MGYB-PENDING",
        )
        result = lookup_or_mint_cbgc(
            contig_accession=contig.accession,
            start_pos=1000,
            end_pos=10_999,
            cbgc=cbgc,
        )
        assert result.minted is True
        assert result.accession.startswith("MGYB-")
        # MGYB- + 6 Crockford chars = 11 total
        assert len(result.accession) == 11

    def test_identity_tuple_reuses_existing(self):
        contig = DashboardContigFactory()
        first = lookup_or_mint_cbgc(
            contig_accession=contig.accession,
            start_pos=1000,
            end_pos=10_999,
        )
        second = lookup_or_mint_cbgc(
            contig_accession=contig.accession,
            start_pos=1000,
            end_pos=10_999,
        )
        assert first.accession == second.accession
        assert first.minted is True
        assert second.minted is False

    def test_different_coords_get_different_accessions(self):
        contig = DashboardContigFactory()
        a = lookup_or_mint_cbgc(
            contig_accession=contig.accession,
            start_pos=1000, end_pos=10_999,
        )
        b = lookup_or_mint_cbgc(
            contig_accession=contig.accession,
            start_pos=20_000, end_pos=30_000,
        )
        assert a.accession != b.accession

    def test_relinks_current_cbgc_on_rebuild(self):
        contig = DashboardContigFactory()
        first_cbgc = ConsensusBgc.objects.create(
            contig=contig, bgc_range=(1000, 11_000), accession="MGYB-PENDING",
        )
        first = lookup_or_mint_cbgc(
            contig_accession=contig.accession,
            start_pos=1000, end_pos=10_999,
            cbgc=first_cbgc,
        )
        # Simulate rebuild: a brand-new cBGC row for the same identity tuple.
        first_cbgc.delete()
        second_cbgc = ConsensusBgc.objects.create(
            contig=contig, bgc_range=(1000, 11_000), accession="MGYB-PENDING",
        )
        second = lookup_or_mint_cbgc(
            contig_accession=contig.accession,
            start_pos=1000, end_pos=10_999,
            cbgc=second_cbgc,
        )
        assert second.accession == first.accession
        assert second.minted is False
        # Registry row points at the new cBGC.
        registry = AccessionRegistry.objects.get(accession=second.accession)
        assert registry.current_cbgc_id == second_cbgc.id


# ── iBGC mint ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestLookupOrMintIbgc:
    def test_accession_is_cbgc_dash_two_chars(self):
        cbgc = ConsensusBgcFactory(_start=1000, _end=11_000)
        ibgc = IntegratedBgc.objects.create(
            cbgc=cbgc, contig=cbgc.contig,
            bgc_range=(1500, 4500), accession="MGYB-PENDING-PENDING",
            source_tools=["antiSMASH"],
        )
        result = lookup_or_mint_ibgc(
            cbgc=cbgc,
            contig_accession=cbgc.contig.accession,
            start_pos=1500, end_pos=4499,
            ibgc=ibgc,
        )
        assert result.minted is True
        assert result.accession.startswith(f"{cbgc.accession}-")
        # cbgc accession + "-" + 2 chars
        assert len(result.accession) == len(cbgc.accession) + 3

    def test_suffix_increments_within_cbgc(self):
        cbgc = ConsensusBgcFactory(_start=1000, _end=20_000)
        first = IntegratedBgcFactory(cbgc=cbgc, _start=1100, _end=4_000)
        second = IntegratedBgcFactory(cbgc=cbgc, _start=5_000, _end=8_000)
        assert first.accession != second.accession
        assert first.accession.startswith(f"{cbgc.accession}-")
        assert second.accession.startswith(f"{cbgc.accession}-")

    def test_identity_tuple_reuses_existing(self):
        cbgc = ConsensusBgcFactory(_start=1000, _end=11_000)
        first = lookup_or_mint_ibgc(
            cbgc=cbgc,
            contig_accession=cbgc.contig.accession,
            start_pos=1500, end_pos=4499,
        )
        second = lookup_or_mint_ibgc(
            cbgc=cbgc,
            contig_accession=cbgc.contig.accession,
            start_pos=1500, end_pos=4499,
        )
        assert first.accession == second.accession
        assert second.minted is False


# ── tombstone_unused ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestTombstoneUnused:
    def test_nulls_current_cbgc_when_row_deleted(self):
        cbgc = ConsensusBgcFactory()
        registry = AccessionRegistry.objects.get(accession=cbgc.accession)
        assert registry.current_cbgc_id == cbgc.id

        cbgc.delete()
        # FK is SET_NULL, so the registry row already has current_cbgc=NULL
        # after the delete; tombstone_unused only matters for entities that
        # were deleted via a different path or by raw SQL. Verify it's a no-op
        # in the natural case and still safe.
        n = tombstone_unused(AccessionEntityType.CBGC)
        assert n == 0
        registry.refresh_from_db()
        assert registry.current_cbgc_id is None

    def test_nulls_current_ibgc_for_stale_registry_rows(self):
        # Build an iBGC, then manually null its current_ibgc and re-attach
        # via raw SQL to simulate a stale registry pointer.
        ibgc = IntegratedBgcFactory(_start=1100, _end=4_000)
        registry = AccessionRegistry.objects.get(accession=ibgc.accession)
        ibgc_id = ibgc.id
        ibgc.delete()
        # Re-attach the registry row to the deleted FK to simulate the stale
        # state tombstone_unused is designed to clean up.
        AccessionRegistry.objects.filter(pk=registry.pk).update(
            current_ibgc_id=ibgc_id,
        )

        n = tombstone_unused(AccessionEntityType.IBGC)
        assert n == 1
        registry.refresh_from_db()
        assert registry.current_ibgc_id is None


# ── resolve ───────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestResolve:
    def test_canonical_cbgc(self):
        cbgc = ConsensusBgcFactory()
        result = resolve(cbgc.accession)
        assert result is not None
        assert result.kind == AccessionEntityType.CBGC
        assert result.current_id == cbgc.id
        assert result.tombstoned is False
        assert result.alias_of is None

    def test_canonical_ibgc(self):
        ibgc = IntegratedBgcFactory(_start=1100, _end=4_000)
        result = resolve(ibgc.accession)
        assert result is not None
        assert result.kind == AccessionEntityType.IBGC
        assert result.current_id == ibgc.id

    def test_alias(self):
        cbgc = ConsensusBgcFactory()
        registry = AccessionRegistry.objects.get(accession=cbgc.accession)
        AccessionAlias.objects.create(
            alias_accession="MGYB99999999", registry=registry,
        )
        result = resolve("MGYB99999999")
        assert result is not None
        assert result.accession == cbgc.accession
        assert result.alias_of == "MGYB99999999"
        assert result.current_id == cbgc.id

    def test_tombstoned(self):
        cbgc = ConsensusBgcFactory()
        accession = cbgc.accession
        cbgc.delete()
        result = resolve(accession)
        assert result is not None
        assert result.tombstoned is True
        assert result.current_id is None

    def test_unknown_returns_none(self):
        assert resolve("MGYB-XXXXXX") is None
