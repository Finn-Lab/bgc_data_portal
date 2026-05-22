"""factory_boy factories for the v2 discovery schema.

All factories create discovery-app rows directly. cBGC / iBGC accessions
are minted via the accession registry so factory output exercises the
real bookkeeping path that production uses.

Usage::

    from tests.factories.discovery_models import IntegratedBgcFactory
    ibgc = IntegratedBgcFactory()  # mints MGYB-XXXXXX-YY, with cBGC + contig

Range-bearing factories accept ``start_pos`` / ``end_pos`` overrides
(inclusive) and convert to the half-open ``int4range`` Postgres stores.
"""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory
from psycopg2.extras import NumericRange

from discovery.models import (
    AssemblySource,
    ConsensusBgc,
    ContigCds,
    ContigDomain,
    DashboardAssembly,
    DashboardContig,
    DashboardDetector,
    IntegratedBgc,
    SourceBgcPrediction,
)
from discovery.services.accession_registry import (
    lookup_or_mint_cbgc,
    lookup_or_mint_ibgc,
)


def _range(start: int, end_inclusive: int) -> NumericRange:
    """Build the half-open ``int4range`` Postgres stores: ``[start, end+1)``."""
    return NumericRange(lower=int(start), upper=int(end_inclusive) + 1, bounds="[)")


# ── Lookup tables ─────────────────────────────────────────────────────────────


class AssemblySourceFactory(DjangoModelFactory):
    class Meta:
        model = AssemblySource
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"source-{n}")


class DashboardDetectorFactory(DjangoModelFactory):
    class Meta:
        model = DashboardDetector
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"antiSMASH v{n}.0")
    tool = "antiSMASH"
    version = factory.Sequence(lambda n: f"{n}.0.0")
    tool_name_code = "ANT"
    version_sort_key = factory.Sequence(lambda n: n)


# ── Identity chain ────────────────────────────────────────────────────────────


class DashboardAssemblyFactory(DjangoModelFactory):
    class Meta:
        model = DashboardAssembly

    assembly_accession = factory.Sequence(lambda n: f"GCA_{n:09d}.1")
    organism_name = factory.Sequence(lambda n: f"Test organism {n}")
    source = factory.SubFactory(AssemblySourceFactory)
    biome_path = "root.Environmental.Soil"
    assembly_size_mb = 5.0


class DashboardContigFactory(DjangoModelFactory):
    class Meta:
        model = DashboardContig

    assembly = factory.SubFactory(DashboardAssemblyFactory)
    sequence_sha256 = factory.Sequence(lambda n: f"{n:064x}")
    accession = factory.Sequence(lambda n: f"contig_{n}")
    length = 100_000
    taxonomy_path = "Bacteria.Actinomycetota"


# ── cBGC / iBGC (mint via registry to exercise the production path) ───────────


class ConsensusBgcFactory(DjangoModelFactory):
    """Creates a cBGC and its registry row; ``accession`` is overwritten on save."""

    class Meta:
        model = ConsensusBgc
        skip_postgeneration_save = True

    contig = factory.SubFactory(DashboardContigFactory)
    accession = "MGYB-PENDING"  # overwritten post-build
    bgc_range = factory.LazyAttribute(lambda obj: _range(obj._start, obj._end))

    class Params:
        # Tests override these; defaults give a 10 kb window starting at 1000.
        _start = 1000
        _end = 11_000

    @factory.post_generation
    def _mint(self, create, extracted, **kwargs):
        if not create:
            return
        result = lookup_or_mint_cbgc(
            contig_accession=self.contig.accession,
            start_pos=self.bgc_range.lower,
            end_pos=self.bgc_range.upper - 1,
            cbgc=self,
        )
        if result.accession != self.accession:
            self.accession = result.accession
            self.save(update_fields=["accession"])


class IntegratedBgcFactory(DjangoModelFactory):
    """Creates an iBGC inside an auto-generated cBGC and mints its registry row."""

    class Meta:
        model = IntegratedBgc
        skip_postgeneration_save = True

    cbgc = factory.SubFactory(ConsensusBgcFactory)
    contig = factory.LazyAttribute(lambda obj: obj.cbgc.contig)
    accession = "MGYB-PENDING-PENDING"
    bgc_range = factory.LazyAttribute(lambda obj: _range(obj._start, obj._end))
    source_tools = factory.LazyFunction(lambda: ["antiSMASH"])

    class Params:
        # By default land inside the parent cBGC's range; override for custom layouts.
        _start = factory.LazyAttribute(lambda obj: obj.factory_parent.cbgc.bgc_range.lower)
        _end = factory.LazyAttribute(
            lambda obj: obj.factory_parent.cbgc.bgc_range.upper - 1
        )

    @factory.post_generation
    def _mint(self, create, extracted, **kwargs):
        if not create:
            return
        result = lookup_or_mint_ibgc(
            cbgc=self.cbgc,
            contig_accession=self.contig.accession,
            start_pos=self.bgc_range.lower,
            end_pos=self.bgc_range.upper - 1,
            ibgc=self,
        )
        if result.accession != self.accession:
            self.accession = result.accession
            self.save(update_fields=["accession"])


# ── Source predictions ────────────────────────────────────────────────────────


class SourceBgcPredictionFactory(DjangoModelFactory):
    class Meta:
        model = SourceBgcPrediction

    assembly = factory.LazyAttribute(lambda obj: obj.contig.assembly)
    contig = factory.SubFactory(DashboardContigFactory)
    prediction_accession = factory.Sequence(lambda n: f"MGYB-AAAAAA.ANT.{n:02}")
    bgc_range = factory.LazyAttribute(lambda obj: _range(obj._start, obj._end))
    is_partial = False
    is_validated = False
    detector = factory.SubFactory(DashboardDetectorFactory)

    class Params:
        _start = 1000
        _end = 11_000


# ── CDS / domains (contig-anchored) ───────────────────────────────────────────


class ContigCdsFactory(DjangoModelFactory):
    class Meta:
        model = ContigCds

    contig = factory.SubFactory(DashboardContigFactory)
    cds_range = factory.LazyAttribute(lambda obj: _range(obj._start, obj._end))
    strand = 1
    protein_id_str = factory.Sequence(lambda n: f"protein_{n}")
    protein_length = 300

    class Params:
        _start = 1000
        _end = 1900


class ContigDomainFactory(DjangoModelFactory):
    class Meta:
        model = ContigDomain

    cds = factory.SubFactory(ContigCdsFactory)
    contig = factory.LazyAttribute(lambda obj: obj.cds.contig)
    domain_acc = factory.Sequence(lambda n: f"PF{n:05d}")
    domain_name = factory.Sequence(lambda n: f"domain {n}")
    domain_description = ""
    ref_db = "PFAM"
    start_position = 1
    end_position = 100
    score = 1e-50
    go_terms = factory.LazyFunction(list)
    go_slim = factory.LazyFunction(list)
