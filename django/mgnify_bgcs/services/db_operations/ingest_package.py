from __future__ import annotations

import gzip
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, cast

try:
    import orjson as json  # type: ignore
except Exception:
    import json  # pragma: no cover - fallback for type checker

try:
    from pgvector import Vector  # type: ignore[import]
except Exception:  # pragma: no cover - fallback for type checker

    class Vector(list):
        """Runtime stub for pgvector.Vector when package not installed."""

        pass


from ...models import (
    Assembly,
    Biome,
    Bgc,
    BgcBgcClass,
    BgcClass,
    BgcDetector,
    Contig,
    GeneCaller,
    Cds,
    Domain,
    Protein,
    ProteinDomain,
    Study,
)

from ...ingestion_schemas import (
    StudyRow,
    BiomeRow,
    AssemblyRow,
    ContigRow,
    BgcRow,
    ProteinRow,
    DomainRow,
    CdsRow,
    BgcClassRow,
    BgcDetectorRow,
    ProteinDomainRow,
    GeneCallerRow,
)

from .helpers import _bulk_get_or_create, BULK_INSERT_SIZE
from ...utils.helpers import normalize_class_distribution_dict


def _as_dict(obj: Any) -> dict:
    """Return a dict representation for a payload-like object.

    Accepts dicts, Pydantic models (model_dump), or objects with `.payload`.
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    # pydantic v2
    if hasattr(obj, "model_dump"):
        try:
            return cast(dict, obj.model_dump())
        except Exception:
            pass
    if hasattr(obj, "payload"):
        p = getattr(obj, "payload")
        if isinstance(p, dict):
            return p
        try:
            return cast(dict, p)
        except Exception:
            pass
    try:
        return dict(obj)
    except Exception:
        return {}


def ingest_package(package_path: str) -> dict:
    """Perform the heavy ingestion work for a package file.

    Returns a summary dict with counts and touched contig ids.
    """
    package = Path(package_path)
    if not package.exists():
        raise FileNotFoundError(package)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with gzip.open(package, "rt") as fh:
        for line in fh:
            raw = json.loads(line)
            kind = raw["kind"]
            row_classes = {
                "study": StudyRow,
                "biome": BiomeRow,
                "assembly": AssemblyRow,
                "contig": ContigRow,
                "bgc": BgcRow,
                "protein": ProteinRow,
                "domain": DomainRow,
                "cds": CdsRow,
                "bgc_class": BgcClassRow,
                "bgc_detector": BgcDetectorRow,
                "gene_caller": GeneCallerRow,
                "protein_domain": ProteinDomainRow,
            }

            row_class = row_classes.get(kind)
            if not row_class:
                raise ValueError(f"Unknown kind: {kind}")

            # row may be a Pydantic model; cast to Any for attribute access
            row = row_class(**raw)
            payload = getattr(row, "payload", None)
            if payload is None:
                # fallback: if the model provides model_dump, use it
                payload = getattr(row, "model_dump", lambda: raw.get("payload"))()
            buckets[kind].append(cast(dict[str, Any], payload))

    # Extract Studies & Biomes from assembly rows
    for a in buckets.get("assembly", []):
        a_d = _as_dict(a)
        study_accession = a_d.get("study_accession")
        biome_lineage = a_d.get("biome_lineage")
        if study_accession:
            row = StudyRow(
                **{"kind": "study", "payload": {"accession": study_accession}}
            )
            buckets["study"].append(cast(dict[str, Any], _as_dict(row.payload)))
        if biome_lineage:
            row = BiomeRow(**{"kind": "biome", "payload": {"lineage": biome_lineage}})
            buckets["biome"].append(cast(dict[str, Any], _as_dict(row.payload)))

    studies = _bulk_get_or_create(Study, buckets.get("study", []), key="accession")
    biomes = _bulk_get_or_create(Biome, buckets.get("biome", []), key="lineage")

    # Assemblies
    assembly_dicts = []
    for a in buckets.get("assembly", []):
        a_d = _as_dict(a)
        a_d["study"] = studies.get(a_d.get("study_accession"))
        a_d["biome"] = biomes.get(a_d.get("biome_lineage"))
        a_d.pop("study_accession", None)
        a_d.pop("biome_lineage", None)
        assembly_dicts.append(a_d)

    assemblies = _bulk_get_or_create(Assembly, assembly_dicts, key="accession")

    # BGC-level look-ups
    bgc_detectors = _bulk_get_or_create(
        BgcDetector, buckets.get("bgc_detector", []), key="name"
    )
    bgc_classes = _bulk_get_or_create(
        BgcClass, buckets.get("bgc_class", []), key="name"
    )
    gene_callers = _bulk_get_or_create(
        GeneCaller, buckets.get("gene_caller", []), key="name"
    )

    # Contigs
    contig_rows, seq_hashes = [], []
    for c in buckets.get("contig", []):
        c_obj = _as_dict(c)
        h = c_obj.get("sequence_sha256")
        seq_hashes.append(h)
        contig_rows.append(
            Contig(
                sequence_sha256=h,
                sequence=(
                    c_obj.get("sequence")
                    if isinstance(c_obj, dict)
                    else getattr(c, "sequence")
                ),
                name=(
                    c_obj.get("name") if isinstance(c_obj, dict) else getattr(c, "name")
                ),
                length=(
                    c_obj.get("length")
                    if isinstance(c_obj, dict)
                    else getattr(c, "length")
                ),
                source_organism=(
                    c_obj.get("source_organism")
                    if isinstance(c_obj, dict)
                    else getattr(c, "source_organism")
                ),
                mgyc=(
                    c_obj.get("mgyc") if isinstance(c_obj, dict) else getattr(c, "mgyc")
                ),
                assembly=assemblies.get(
                    c_obj.get("assembly_accession")
                    if isinstance(c_obj, dict)
                    else getattr(c, "assembly_accession")
                ),
            )
        )

    Contig.objects.bulk_create(
        contig_rows, ignore_conflicts=True, batch_size=BULK_INSERT_SIZE
    )
    contigs = {
        x.sequence_sha256: x
        for x in Contig.objects.filter(sequence_sha256__in=seq_hashes)
    }

    # Proteins
    protein_rows, p_hashes = [], []
    for p in buckets.get("protein", []):
        p_obj = _as_dict(p)
        h = p_obj.get("sequence_sha256")
        p_hashes.append(h)
        embedding = p_obj.get("embedding")
        protein_rows.append(
            Protein(
                sequence=(
                    p_obj.get("sequence")
                    if isinstance(p_obj, dict)
                    else getattr(p, "sequence")
                ),
                sequence_sha256=h,
                embedding=Vector(embedding) if embedding is not None else None,
                cluster_representative=(
                    p_obj.get("cluster_representative")
                    if isinstance(p_obj, dict)
                    else getattr(p, "cluster_representative", None)
                ),
            )
        )
    Protein.objects.bulk_create(
        protein_rows, ignore_conflicts=True, batch_size=BULK_INSERT_SIZE
    )
    proteins = {
        x.sequence_sha256: x
        for x in Protein.objects.filter(sequence_sha256__in=p_hashes)
    }

    # Domain & ProteinDomain
    domains = _bulk_get_or_create(Domain, buckets.get("domain", []), key="acc")
    ppf_rows: list[ProteinDomain] = []
    for link in buckets.get("protein_domain", []):
        link_obj = _as_dict(link)
        ppf_rows.append(
            ProteinDomain(
                # coerce keys to str safely
                protein=(
                    proteins.get(str(link_obj.get("protein_sequence_sha256") or ""))
                    if link_obj.get("protein_sequence_sha256") is not None
                    else None
                ),
                domain=(
                    domains.get(str(link_obj.get("domain_acc") or ""))
                    if link_obj.get("domain_acc") is not None
                    else None
                ),
                start_position=link_obj.get("start_position"),
                end_position=link_obj.get("end_position"),
                score=link_obj.get("score"),
            )
        )
    ProteinDomain.objects.bulk_create(
        ppf_rows, ignore_conflicts=True, batch_size=BULK_INSERT_SIZE
    )

    # BGCs & BGC-Class
    bgcs: Dict[int, Bgc] = {}
    for ix, b in enumerate(buckets.get("bgc", [])):
        b_obj = _as_dict(b)
        # helpers to safely access attributes/keys
        contig_key = str(b_obj.get("contig_sequence_sha256") or "")
        det_key = str(b_obj.get("detector_name") or "")
        contig_ref = contigs.get(contig_key) if contig_key else None
        detector_ref = bgc_detectors.get(det_key) if det_key else None
        identifier = b_obj.get("identifier")
        start = b_obj.get("start_position")
        end = b_obj.get("end_position")
        metadata = b_obj.get("metadata", {})
        compounds = b_obj.get("compounds", [])
        is_partial = (
            b_obj.get("is_partial", True)
            if isinstance(b_obj.get("is_partial", True), bool)
            else True
        )
        embedding = b_obj.get("embedding", None)
        bgc, created = Bgc.objects.get_or_create(
            contig=contig_ref,
            detector=detector_ref,
            identifier=identifier,
            start_position=start,
            end_position=end,
            defaults={
                "metadata": metadata,
                "compounds": compounds,
                "is_partial": is_partial,
                "embedding": embedding,
            },
        )
        if created:
            bgcs[ix] = bgc

    bgc_bgcclass_rows: list[BgcBgcClass] = []
    for ix, b in enumerate(buckets.get("bgc", [])):
        if ix in bgcs:
            b_obj = _as_dict(b)
            classes = b_obj.get("classes")
            normalized_classes = normalize_class_distribution_dict(
                {cl: 1 for cl in classes} if classes else {}
            )
            for _class in normalized_classes.keys():
                bgc_bgcclass_rows.append(
                    BgcBgcClass(
                        bgc=bgcs[ix],
                        bgc_class=bgc_classes[_class],
                    )
                )
    BgcBgcClass.objects.bulk_create(
        bgc_bgcclass_rows, ignore_conflicts=True, batch_size=BULK_INSERT_SIZE
    )

    # CDS
    md_rows: list[Cds] = []
    for m in buckets.get("cds", []):
        m_obj = _as_dict(m)
        md_rows.append(
            Cds(
                protein=(
                    proteins.get(str(m_obj.get("protein_sequence_sha256") or ""))
                    if m_obj.get("protein_sequence_sha256") is not None
                    else None
                ),
                contig=(
                    contigs.get(str(m_obj.get("contig_sequence_sha256") or ""))
                    if m_obj.get("contig_sequence_sha256") is not None
                    else None
                ),
                gene_caller=(
                    gene_callers.get(str(m_obj.get("gene_caller_name") or ""))
                    if m_obj.get("gene_caller_name") is not None
                    else None
                ),
                start_position=m_obj.get("start_position"),
                end_position=m_obj.get("end_position"),
                strand=m_obj.get("strand"),
                protein_identifier=m_obj.get("protein_identifier"),
                pipeline_version=m_obj.get("pipeline_version"),
            )
        )
    Cds.objects.bulk_create(md_rows, ignore_conflicts=True, batch_size=BULK_INSERT_SIZE)

    touched_contig_ids = [c.id for c in contigs.values()]

    return {
        "studies": len(studies),
        "assemblies": len(assemblies),
        "contigs": len(contigs),
        "proteins": len(proteins),
        "bgcs": len(bgcs),
        "touched_contig_ids": touched_contig_ids,
    }
