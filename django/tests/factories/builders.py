"""
DatasetBuilder — builds a full relational dataset from a YAML manifest.

Used by both pytest fixtures (conftest.py) and the seed_data management command.
"""

import random
from pathlib import Path

import yaml

from mgnify_bgcs.models import BgcBgcClass
from tests.factories.models import (
    AssemblyFactory,
    BgcClassFactory,
    BgcDetectorFactory,
    BgcFactory,
    CdsFactory,
    ContigFactory,
    GeneCallerFactory,
    ProteinDomainFactory,
    ProteinFactory,
    StudyFactory,
)

MANIFESTS_DIR = Path(__file__).parent / "manifests"


def resolve_manifest(manifest: str | Path) -> Path:
    """Accept a manifest name (e.g. 'small'), a stem, or a full path."""
    p = Path(manifest)
    if p.suffix:
        # already has extension — treat as path
        return p if p.is_absolute() else MANIFESTS_DIR / p
    # bare name — look in manifests dir
    candidate = MANIFESTS_DIR / f"{manifest}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"No manifest found for {manifest!r}. Expected {candidate}")


class DatasetBuilder:
    def __init__(self, manifest_path: str | Path):
        path = resolve_manifest(manifest_path)
        self.spec = yaml.safe_load(path.read_text())

    def build(self) -> dict:
        """
        Builds the full dataset and returns a summary dict with counts.
        """
        spec = self.spec

        # Ensure at least one GeneCaller exists (get_or_create semantics)
        GeneCallerFactory(name="Prodigal")
        GeneCallerFactory(name="Pyrodigal")

        # Shared lookup objects
        classes = [BgcClassFactory(name=n) for n in spec["bgc_classes"]]
        detectors = [
            BgcDetectorFactory(name=t, tool=t) for t in spec["detectors"]
        ]

        counts = {
            "studies": 0,
            "assemblies": 0,
            "contigs": 0,
            "bgcs": 0,
            "proteins": 0,
            "domains": 0,
        }

        for _ in range(spec["studies"]):
            study = StudyFactory()
            counts["studies"] += 1

            for _ in range(spec["assemblies_per_study"]):
                assembly = AssemblyFactory(study=study)
                counts["assemblies"] += 1

                for _ in range(spec["contigs_per_assembly"]):
                    contig = ContigFactory(assembly=assembly)
                    counts["contigs"] += 1

                    for _ in range(spec["bgcs_per_contig"]):
                        bgc = BgcFactory(
                            contig=contig,
                            detector=random.choice(detectors),
                        )
                        n_classes = min(random.randint(1, 2), len(classes))
                        chosen = random.sample(classes, k=n_classes)
                        BgcBgcClass.objects.bulk_create(
                            [BgcBgcClass(bgc=bgc, bgc_class=cls) for cls in chosen],
                            ignore_conflicts=True,
                        )
                        counts["bgcs"] += 1

                        cds_count = spec["cds_per_bgc"]
                        bgc_len = bgc.end_position - bgc.start_position
                        slot_size = max(1, bgc_len // cds_count)

                        for ci in range(cds_count):
                            protein = ProteinFactory()
                            counts["proteins"] += 1

                            slot_start = bgc.start_position + ci * slot_size
                            margin = max(11, slot_size // 4)
                            cds_start = slot_start + random.randint(10, margin)
                            cds_len = min(500, slot_size - 60)
                            cds_end = cds_start + random.randint(200, max(200, cds_len))
                            cds_end = min(cds_end, bgc.end_position)

                            CdsFactory(
                                contig=contig,
                                protein=protein,
                                start_position=cds_start,
                                end_position=cds_end,
                            )

                            for _ in range(spec["pfam_domains_per_protein"]):
                                ProteinDomainFactory(protein=protein)
                                counts["domains"] += 1

        return counts
