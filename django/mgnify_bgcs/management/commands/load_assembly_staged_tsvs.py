from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction

from mgnify_bgcs.models import (
    Assembly,
    Biome,
    Bgc,
    BgcBgcClass,
    BgcClass,
    BgcDetector,
    Cds,
    Contig,
    Domain,
    GeneCaller,
    Protein,
    ProteinDomain,
    Study,
)

csv.field_size_limit(sys.maxsize)

REQUIRED_FILES = [
    "assemblies.tsv",
    "bgc_bgc_classes.tsv",
    "bgc_classes.tsv",
    "bgc_detectors.tsv",
    "bgcs.tsv",
    "biomes.tsv",
    "cds.tsv",
    "contigs.tsv",
    "domains.tsv",
    "gene_callers.tsv",
    "protein_domains.tsv",
    "proteins.tsv",
    "studies.tsv",
]


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return [row for row in reader]


def _parse_json_maybe(s: Optional[str]) -> Optional[Any]:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    return json.loads(s)


def _to_int_maybe(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    return int(s)


def _to_float_maybe(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    return float(s)


def _to_bool(s: Any) -> bool:
    if s is None:
        return False
    if isinstance(s, bool):
        return s
    return str(s).strip().lower() in {"true", "t", "1", "yes", "y"}


def _chunked(seq: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _bulk_upsert(
    model: type[models.Model],
    objs: Sequence[models.Model],
    *,
    unique_fields: Sequence[str],
    update_fields: Sequence[str],
    batch_size: int,
) -> None:
    if not objs:
        return

    if not update_fields:
        for batch in _chunked(objs, batch_size):
            model.objects.bulk_create(
                batch,
                batch_size=batch_size,
                ignore_conflicts=True,
            )
        return

    for batch in _chunked(objs, batch_size):
        model.objects.bulk_create(
            batch,
            batch_size=batch_size,
            update_conflicts=True,
            unique_fields=list(unique_fields),
            update_fields=list(update_fields),
        )


def _preload_map(
    model: type[models.Model],
    keys: Iterable[Any],
    *,
    field_name: str,
) -> dict[Any, models.Model]:
    key_list = list({k for k in keys if k is not None and str(k).strip() != ""})
    if not key_list:
        return {}
    return model.objects.filter(**{f"{field_name}__in": key_list}).in_bulk(
        field_name=field_name
    )


def _ensure_dir_has_files(genome_dir: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (genome_dir / name).exists()]
    if missing:
        raise CommandError(f"Missing files in {genome_dir}: {', '.join(missing)}")


def _load_one_genome_dir(
    genome_dir: Path, *, batch_size: int, dry_run: bool
) -> dict[str, int]:
    """
    Loads one genome subdirectory in a single transaction.
    Sequences are immutable -> we do NOT update large sequence text fields on conflict.
    """
    _ensure_dir_has_files(genome_dir)

    assemblies_rows = _read_tsv(genome_dir / "assemblies.tsv")
    studies_rows = _read_tsv(genome_dir / "studies.tsv")
    biomes_rows = _read_tsv(genome_dir / "biomes.tsv")
    contigs_rows = _read_tsv(genome_dir / "contigs.tsv")

    detectors_rows = _read_tsv(genome_dir / "bgc_detectors.tsv")
    bgc_classes_rows = _read_tsv(genome_dir / "bgc_classes.tsv")
    bgcs_rows = _read_tsv(genome_dir / "bgcs.tsv")
    bgc_bgc_classes_rows = _read_tsv(genome_dir / "bgc_bgc_classes.tsv")

    gene_callers_rows = _read_tsv(genome_dir / "gene_callers.tsv")
    proteins_rows = _read_tsv(genome_dir / "proteins.tsv")
    domains_rows = _read_tsv(genome_dir / "domains.tsv")
    protein_domains_rows = _read_tsv(genome_dir / "protein_domains.tsv")
    cds_rows = _read_tsv(genome_dir / "cds.tsv")

    # Optional early exit for dry-run after parsing/validation
    if dry_run:
        return {
            "studies": len(studies_rows),
            "biomes": len(biomes_rows),
            "assemblies": len(assemblies_rows),
            "contigs": len(contigs_rows),
            "bgc_detectors": len(detectors_rows),
            "bgc_classes": len(bgc_classes_rows),
            "bgcs": len(bgcs_rows),
            "bgc_bgc_classes": len(bgc_bgc_classes_rows),
            "gene_callers": len(gene_callers_rows),
            "domains": len(domains_rows),
            "proteins": len(proteins_rows),
            "protein_domains": len(protein_domains_rows),
            "cds": len(cds_rows),
        }

    with transaction.atomic():
        # ---- Dimension tables (no FKs) ----
        studies = [Study(accession=r["accession"].strip()) for r in studies_rows]
        _bulk_upsert(
            Study,
            studies,
            unique_fields=["accession"],
            update_fields=[],
            batch_size=batch_size,
        )

        biomes = [
            Biome(lineage=(r.get("lineage") or "root").strip()) for r in biomes_rows
        ]
        _bulk_upsert(
            Biome,
            biomes,
            unique_fields=["lineage"],
            update_fields=[],
            batch_size=batch_size,
        )

        detectors = [
            BgcDetector(
                name=r["name"].strip(),
                tool=(r.get("tool") or None),
                version=(r.get("version") or None),
            )
            for r in detectors_rows
        ]
        _bulk_upsert(
            BgcDetector,
            detectors,
            unique_fields=["name"],
            update_fields=["tool", "version"],
            batch_size=batch_size,
        )

        bgc_classes = [BgcClass(name=r["name"].strip()) for r in bgc_classes_rows]
        _bulk_upsert(
            BgcClass,
            bgc_classes,
            unique_fields=["name"],
            update_fields=[],
            batch_size=batch_size,
        )

        gene_callers = [
            GeneCaller(
                name=r["name"].strip(),
                tool=(r.get("tool") or None),
                version=(r.get("version") or None),
            )
            for r in gene_callers_rows
        ]
        _bulk_upsert(
            GeneCaller,
            gene_callers,
            unique_fields=["name"],
            update_fields=["tool", "version"],
            batch_size=batch_size,
        )

        domains = [
            Domain(
                acc=r["acc"].strip(),
                name=r["name"].strip(),
                ref_db=r["ref_db"].strip(),
                description=(r.get("description") or None),
            )
            for r in domains_rows
        ]
        _bulk_upsert(
            Domain,
            domains,
            unique_fields=["acc"],
            update_fields=["name", "ref_db", "description"],
            batch_size=batch_size,
        )

        # ---- Preload FK maps ----
        study_map = _preload_map(
            Study,
            (r.get("study_accession") for r in assemblies_rows),
            field_name="accession",
        )
        biome_map = _preload_map(
            Biome,
            (r.get("biome_lineage") for r in assemblies_rows),
            field_name="lineage",
        )

        detector_map = _preload_map(
            BgcDetector, (r.get("detector_name") for r in bgcs_rows), field_name="name"
        )
        bgc_class_map = _preload_map(
            BgcClass,
            (r.get("bgc_class_name") for r in bgc_bgc_classes_rows),
            field_name="name",
        )

        gene_caller_map = _preload_map(
            GeneCaller, (r.get("gene_caller_name") for r in cds_rows), field_name="name"
        )
        domain_map = _preload_map(
            Domain,
            (r.get("domain_acc") for r in protein_domains_rows),
            field_name="acc",
        )

        # ---- Assemblies ----
        assemblies = []
        for r in assemblies_rows:
            accession = r["accession"].strip()
            assemblies.append(
                Assembly(
                    accession=accession,
                    collection=(r.get("collection") or None),
                    study=study_map.get(
                        (r.get("study_accession") or "").strip() or None
                    ),
                    biome=biome_map.get((r.get("biome_lineage") or "").strip() or None),
                )
            )
        _bulk_upsert(
            Assembly,
            assemblies,
            unique_fields=["accession"],
            update_fields=["collection", "study", "biome"],
            batch_size=batch_size,
        )
        assembly_map = _preload_map(
            Assembly, (r["accession"] for r in assemblies_rows), field_name="accession"
        )

        # ---- Contigs ----
        # sequence is immutable -> do NOT update it on conflict
        contigs = []
        for r in contigs_rows:
            sha = r["sequence_sha256"].strip()
            contigs.append(
                Contig(
                    sequence_sha256=sha,
                    sequence=r["sequence"],  # inserted once
                    length=_to_int_maybe(r.get("length")),
                    mgyc=(r.get("mgyc") or None),
                    accession=(r.get("accession") or None),
                    name=(r.get("name") or None),
                    assembly=assembly_map.get(
                        (r.get("assembly_accession") or "").strip() or None
                    ),
                    source_organism=_parse_json_maybe(r.get("source_organism")) or {},
                )
            )
        _bulk_upsert(
            Contig,
            contigs,
            unique_fields=["sequence_sha256"],
            update_fields=[
                "length",
                "mgyc",
                "accession",
                "name",
                "assembly",
                "source_organism",
            ],
            batch_size=batch_size,
        )
        contig_map = _preload_map(
            Contig,
            (r["sequence_sha256"] for r in contigs_rows),
            field_name="sequence_sha256",
        )

        # ---- Proteins ----
        # sequence is immutable -> do NOT update it on conflict
        proteins = []
        for r in proteins_rows:
            sha = r["sequence_sha256"].strip()
            proteins.append(
                Protein(
                    sequence_sha256=sha,
                    sequence=r["sequence"],  # inserted once
                    mgyp=(r.get("mgyp") or None),
                    cluster_representative=(r.get("cluster_representative") or None),
                )
            )
        _bulk_upsert(
            Protein,
            proteins,
            unique_fields=["sequence_sha256"],
            update_fields=["mgyp", "cluster_representative"],
            batch_size=batch_size,
        )
        protein_map = _preload_map(
            Protein,
            (r["sequence_sha256"] for r in proteins_rows),
            field_name="sequence_sha256",
        )

        # ---- BGCs ----
        bgc_objs = []
        for r in bgcs_rows:
            contig = contig_map.get(r["contig_sequence_sha256"].strip())
            det = detector_map.get(r["detector_name"].strip())
            if not contig or not det:
                continue
            bgc_objs.append(
                Bgc(
                    contig=contig,
                    detector=det,
                    identifier=(r.get("identifier") or None),
                    start_position=int(r["start_position"]),
                    end_position=int(r["end_position"]),
                    metadata=_parse_json_maybe(r.get("metadata")),
                    is_partial=_to_bool(r.get("is_partial")),
                )
            )

        _bulk_upsert(
            Bgc,
            bgc_objs,
            unique_fields=["contig", "start_position", "end_position", "detector"],
            update_fields=["identifier", "metadata", "is_partial"],
            batch_size=batch_size,
        )

        # Re-fetch BGCs for linking (by contig+detector pairs; then key in memory)
        contig_ids = {b.contig_id for b in bgc_objs}
        detector_ids = {b.detector_id for b in bgc_objs}
        bgc_qs = Bgc.objects.filter(
            contig_id__in=contig_ids, detector_id__in=detector_ids
        ).only("id", "contig_id", "detector_id", "start_position", "end_position")
        bgc_key_to_id = {
            (b.contig_id, b.detector_id, b.start_position, b.end_position): b.id
            for b in bgc_qs
        }

        # ---- BgcBgcClass through table ----
        bgc_class_links: list[BgcBgcClass] = []
        for r in bgc_bgc_classes_rows:
            contig = contig_map.get(r["contig_sequence_sha256"].strip())
            det = detector_map.get(r["detector_name"].strip())
            cls = bgc_class_map.get(r["bgc_class_name"].strip())
            if not contig or not det or not cls:
                continue

            key = (contig.id, det.id, int(r["start_position"]), int(r["end_position"]))
            bgc_id = bgc_key_to_id.get(key)
            if not bgc_id:
                continue
            bgc_class_links.append(BgcBgcClass(bgc_id=bgc_id, bgc_class=cls))

        BgcBgcClass.objects.bulk_create(
            bgc_class_links,
            ignore_conflicts=True,
            batch_size=batch_size,
        )

        # ---- ProteinDomain through table ----
        prot_dom_links: list[ProteinDomain] = []
        for r in protein_domains_rows:
            prot = protein_map.get(r["protein_sequence_sha256"].strip())
            dom = domain_map.get(r["domain_acc"].strip())
            if not prot or not dom:
                continue
            prot_dom_links.append(
                ProteinDomain(
                    protein=prot,
                    domain=dom,
                    start_position=int(r["start_position"]),
                    end_position=int(r["end_position"]),
                    score=_to_float_maybe(r.get("score")),
                )
            )

        ProteinDomain.objects.bulk_create(
            prot_dom_links,
            ignore_conflicts=True,
            batch_size=batch_size,
        )

        # ---- CDS ----
        cds_objs: list[Cds] = []
        for r in cds_rows:
            contig = contig_map.get(r["contig_sequence_sha256"].strip())
            prot = protein_map.get(r["protein_sequence_sha256"].strip())
            caller_name = (r.get("gene_caller_name") or "").strip() or None
            caller = gene_caller_map.get(caller_name) if caller_name else None
            if not contig or not prot:
                continue

            cds_objs.append(
                Cds(
                    contig=contig,
                    protein=prot,
                    gene_caller=caller,
                    start_position=int(r["start_position"]),
                    end_position=int(r["end_position"]),
                    strand=int(r["strand"]),
                    protein_identifier=(r.get("protein_identifier") or None),
                    pipeline_version=(r.get("pipeline_version") or None),
                )
            )

        _bulk_upsert(
            Cds,
            cds_objs,
            unique_fields=[
                "contig",
                "start_position",
                "end_position",
                "strand",
                "protein",
                "gene_caller",
            ],
            update_fields=["protein_identifier", "pipeline_version"],
            batch_size=batch_size,
        )

    return {
        "studies": len(studies_rows),
        "biomes": len(biomes_rows),
        "assemblies": len(assemblies_rows),
        "contigs": len(contigs_rows),
        "bgc_detectors": len(detectors_rows),
        "bgc_classes": len(bgc_classes_rows),
        "bgcs": len(bgcs_rows),
        "bgc_bgc_classes": len(bgc_bgc_classes_rows),
        "gene_callers": len(gene_callers_rows),
        "domains": len(domains_rows),
        "proteins": len(proteins_rows),
        "protein_domains": len(protein_domains_rows),
        "cds": len(cds_rows),
    }


class Command(BaseCommand):
    help = "Load genome TSV subdirectories into Postgres via Django ORM (bulk upserts)."

    def add_arguments(self, parser):
        parser.add_argument(
            "input_dir",
            type=str,
            help="Directory containing per-genome subdirectories (each with the required TSV files).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10_000,
            help="bulk_create batch size (default: 10000).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse/validate input and print counts, but do not write to DB.",
        )
        parser.add_argument(
            "--only",
            type=str,
            default=None,
            help="Comma-separated list of subdirectory names to load (others are skipped).",
        )
        parser.add_argument(
            "--fail-fast",
            action="store_true",
            help="Stop at first failing subdirectory.",
        )

    def handle(self, *args, **options):
        input_dir = Path(options["input_dir"]).expanduser().resolve()
        if not input_dir.exists() or not input_dir.is_dir():
            raise CommandError(
                f"input_dir does not exist or is not a directory: {input_dir}"
            )

        batch_size: int = options["batch_size"]
        dry_run: bool = options["dry_run"]
        fail_fast: bool = options["fail_fast"]

        only_set: Optional[set[str]] = None
        if options["only"]:
            only_set = {s.strip() for s in options["only"].split(",") if s.strip()}

        subdirs = sorted([p for p in input_dir.iterdir() if p.is_dir()])
        if only_set is not None:
            subdirs = [p for p in subdirs if p.name in only_set]

        if not subdirs:
            raise CommandError(f"No genome subdirectories found in: {input_dir}")

        ok = 0
        failed = 0

        for genome_dir in subdirs:
            try:
                counts = _load_one_genome_dir(
                    genome_dir, batch_size=batch_size, dry_run=dry_run
                )
                ok += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{genome_dir.name}: OK "
                        + " ".join([f"{k}={v}" for k, v in counts.items()])
                        + (" (dry-run)" if dry_run else "")
                    )
                )
            except Exception as e:
                failed += 1
                self.stderr.write(self.style.ERROR(f"{genome_dir.name}: FAILED: {e}"))
                if fail_fast:
                    raise

        if failed:
            raise CommandError(f"Completed with failures. ok={ok} failed={failed}")
        self.stdout.write(self.style.SUCCESS(f"Completed. ok={ok} failed={failed}"))
