"""
Seed the discovery app with realistic mock data for dashboard development.

Seeds ALL self-contained discovery models with data that exercises every
field, relationship, and dashboard feature.

Usage:
    python manage.py seed_discovery_data
    python manage.py seed_discovery_data --clear   # wipe discovery tables first
    python manage.py seed_discovery_data --small    # smaller dataset (20 assemblies)
"""

import hashlib
import math
import random

import numpy as np
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from discovery.models import (
    AssemblySource,
    AssemblyType,
    BgcDomain,
    BgcEmbedding,
    CdsSequence,
    ContigSequence,
    DashboardAssembly,
    DashboardBgc,
    DashboardBgcClass,
    DashboardCds,
    DashboardContig,
    DashboardDetector,
    DashboardDomain,
    DashboardGCF,
    DashboardNaturalProduct,
    DashboardRegion,
    NaturalProductChemOntClass,
    PrecomputedStats,
    ProteinEmbedding,
    RegionAccessionAlias,
)
from discovery.services.ingestion.region_assignment import RegionAssigner


# ── Reference data ───────────────────────────────────────────────────────────

_TAXONOMY_POOL = [
    ("Bacteria", "Actinomycetota", "Actinomycetia", "Streptomycetales", "Streptomycetaceae", "Streptomyces", "Streptomyces coelicolor"),
    ("Bacteria", "Actinomycetota", "Actinomycetia", "Micromonosporales", "Micromonosporaceae", "Micromonospora", "Micromonospora sp."),
    ("Bacteria", "Pseudomonadota", "Gammaproteobacteria", "Pseudomonadales", "Pseudomonadaceae", "Pseudomonas", "Pseudomonas fluorescens"),
    ("Bacteria", "Bacillota", "Bacilli", "Bacillales", "Bacillaceae", "Bacillus", "Bacillus subtilis"),
    ("Bacteria", "Cyanobacteriota", "Cyanophyceae", "Nostocales", "Nostocaceae", "Nostoc", "Nostoc punctiforme"),
    ("Bacteria", "Myxococcota", "Myxococcia", "Myxococcales", "Myxococcaceae", "Myxococcus", "Myxococcus xanthus"),
    ("Bacteria", "Planctomycetota", "Planctomycetes", "Planctomycetales", "Planctomycetaceae", "Planctomyces", "Planctomyces brasiliensis"),
    ("Bacteria", "Actinomycetota", "Actinomycetia", "Kitasatosporales", "Kitasatosporaceae", "Kitasatospora", "Kitasatospora setae"),
]

_UMAP_CENTERS = {
    "Polyketide": (-5.0, 3.0),
    "NRP": (4.0, 4.0),
    "RiPP": (0.0, -5.0),
    "Terpene": (-6.0, -4.0),
    "Saccharide": (5.0, -3.0),
    "Alkaloid": (7.0, 1.0),
    "Other": (0.0, 0.0),
}

_BGC_L1_CLASSES = list(_UMAP_CENTERS.keys())

_NP_CLASSES = {
    "Polyketide": {"Macrolide": ["Erythromycin-type", "14-membered"], "Ansamycin": ["Rifamycin"]},
    "NRP": {"Cyclic peptide": ["Lipopeptide", "Glycopeptide"], "Linear peptide": ["Gramicidin"]},
    "RiPP": {"Lanthipeptide": ["Class I", "Class II"], "Thiopeptide": ["Series d"]},
    "Terpene": {"Diterpene": ["Labdane"], "Sesquiterpene": ["Eudesmane"]},
    "Alkaloid": {"Indole": ["Ergoline"], "Isoquinoline": ["Benzylisoquinoline"]},
}

# ChemOnt lineage paths per BGC class.
# Each lineage is a root-to-leaf path through the ontology hierarchy.
# Format: list of (chemont_id, name, base_probability) ordered general→specific.
# The seeder picks 1–2 lineages per NP and annotates all nodes along each path.
#
# Real hierarchy (from ChemOnt_2_1.obo):
#   Chemical entities (9999999) → Organic compounds (0000000)
#     → Phenylpropanoids and polyketides (0000261) → Macrolides (0000147) → Epothilones (0000161)
#     → Organic acids (0000264) → Carboxylic acids (0000265) → Amino acids, peptides (0000013)
#       → Peptides (0000348) → Cyclic peptides (0001995) → Diketopiperazines (0002356)
#     → Lipids (0000012) → Prenol lipids (0000259) → Sesquiterpenoids (0001550)
#     → Alkaloids (0000279) → Indoles (0000211)

_CHEMONT_LINEAGES = {
    "Polyketide": [
        [   # Organic compounds → Phenylpropanoids → Macrolides → Epothilones
            ("CHEMONTID:0000000", "Organic compounds", 0.99),
            ("CHEMONTID:0000261", "Phenylpropanoids and polyketides", 0.90),
            ("CHEMONTID:0000147", "Macrolides and analogues", 0.85),
            ("CHEMONTID:0000161", "Epothilones and analogues", 0.72),
        ],
        [   # Organic compounds → Phenylpropanoids → Coumarins
            ("CHEMONTID:0000000", "Organic compounds", 0.99),
            ("CHEMONTID:0000261", "Phenylpropanoids and polyketides", 0.91),
            ("CHEMONTID:0000145", "Coumarins and derivatives", 0.78),
        ],
        [   # Organic compounds → Phenylpropanoids → Macrolides (stop here)
            ("CHEMONTID:0000000", "Organic compounds", 0.99),
            ("CHEMONTID:0000261", "Phenylpropanoids and polyketides", 0.88),
            ("CHEMONTID:0000147", "Macrolides and analogues", 0.82),
        ],
    ],
    "NRP": [
        [   # Organic compounds → Organic acids → Carboxylic acids → AA/peptides → Peptides → Cyclic peptides
            ("CHEMONTID:0000000", "Organic compounds", 0.99),
            ("CHEMONTID:0000264", "Organic acids and derivatives", 0.96),
            ("CHEMONTID:0000265", "Carboxylic acids and derivatives", 0.93),
            ("CHEMONTID:0000013", "Amino acids, peptides, and analogues", 0.90),
            ("CHEMONTID:0000348", "Peptides", 0.87),
            ("CHEMONTID:0001995", "Cyclic peptides", 0.80),
        ],
        [   # → Cyclic peptides → Cyclic depsipeptides
            ("CHEMONTID:0000013", "Amino acids, peptides, and analogues", 0.92),
            ("CHEMONTID:0000348", "Peptides", 0.88),
            ("CHEMONTID:0001995", "Cyclic peptides", 0.83),
            ("CHEMONTID:0001994", "Cyclic depsipeptides", 0.75),
        ],
        [   # → Cyclic peptides → Diketopiperazines
            ("CHEMONTID:0000013", "Amino acids, peptides, and analogues", 0.91),
            ("CHEMONTID:0000348", "Peptides", 0.86),
            ("CHEMONTID:0001995", "Cyclic peptides", 0.81),
            ("CHEMONTID:0002356", "Diketopiperazines", 0.70),
        ],
    ],
    "RiPP": [
        [   # AA/peptides → Peptides → Cyclic peptides
            ("CHEMONTID:0000013", "Amino acids, peptides, and analogues", 0.93),
            ("CHEMONTID:0000348", "Peptides", 0.88),
            ("CHEMONTID:0001995", "Cyclic peptides", 0.78),
        ],
        [   # Organoheterocyclic → Thiazoles
            ("CHEMONTID:0000002", "Organoheterocyclic compounds", 0.90),
            ("CHEMONTID:0000095", "Thiazoles", 0.74),
        ],
    ],
    "Terpene": [
        [   # Organic compounds → Lipids → Prenol lipids → Sesquiterpenoids
            ("CHEMONTID:0000000", "Organic compounds", 0.99),
            ("CHEMONTID:0000012", "Lipids and lipid-like molecules", 0.95),
            ("CHEMONTID:0000259", "Prenol lipids", 0.90),
            ("CHEMONTID:0001550", "Sesquiterpenoids", 0.82),
        ],
        [   # → Prenol lipids → Diterpenoids → Cembrane diterpenoids
            ("CHEMONTID:0000012", "Lipids and lipid-like molecules", 0.96),
            ("CHEMONTID:0000259", "Prenol lipids", 0.91),
            ("CHEMONTID:0001551", "Diterpenoids", 0.84),
            ("CHEMONTID:0000008", "Cembrane diterpenoids", 0.70),
        ],
        [   # → Prenol lipids → Monoterpenoids
            ("CHEMONTID:0000012", "Lipids and lipid-like molecules", 0.96),
            ("CHEMONTID:0000259", "Prenol lipids", 0.92),
            ("CHEMONTID:0001549", "Monoterpenoids", 0.80),
        ],
    ],
    "Alkaloid": [
        [   # Organic compounds → Alkaloids → Tropane alkaloids
            ("CHEMONTID:0000000", "Organic compounds", 0.99),
            ("CHEMONTID:0000279", "Alkaloids and derivatives", 0.92),
            ("CHEMONTID:0000492", "Tropane alkaloids", 0.78),
        ],
        [   # Organic compounds → Alkaloids → Morphinans
            ("CHEMONTID:0000000", "Organic compounds", 0.99),
            ("CHEMONTID:0000279", "Alkaloids and derivatives", 0.90),
            ("CHEMONTID:0000058", "Morphinans", 0.74),
        ],
        [   # Organoheterocyclic → Indoles
            ("CHEMONTID:0000002", "Organoheterocyclic compounds", 0.95),
            ("CHEMONTID:0000211", "Indoles and derivatives", 0.82),
        ],
    ],
}

_SMILES_POOL = [
    "CC(=O)OC1=CC=CC=C1C(=O)O",
    "CC1=CC=C(C=C1)C(=O)O",
    "C1CCCCC1",
    "CC(=O)NC1=CC=C(C=C1)O",
    "CC1(C)C2CCC1(C)C(=O)C2",
]

_MIBIG_COMPOUNDS = [
    ("Erythromycin", "Polyketide"), ("Vancomycin", "NRP"),
    ("Daptomycin", "NRP"), ("Rifamycin", "Polyketide"),
    ("Avermectin", "Polyketide"), ("Nisin", "RiPP"),
    ("Lanthipeptide X", "RiPP"), ("Geosmin", "Terpene"),
    ("Staurosporine", "Alkaloid"), ("Amphotericin B", "Polyketide"),
]

_PFAM_DOMAIN_POOL = [
    ("PF00109", "Beta-ketoacyl synthase N-terminal", "Pfam"),
    ("PF00698", "Acyl transferase domain", "Pfam"),
    ("PF00550", "Phosphopantetheine attachment site", "Pfam"),
    ("PF00668", "Condensation domain", "Pfam"),
    ("PF00501", "AMP-binding enzyme", "Pfam"),
    ("PF07993", "Male sterility protein", "Pfam"),
    ("PF00975", "Thioesterase domain", "Pfam"),
    ("PF02801", "Beta-ketoacyl synthase C-terminal", "Pfam"),
    ("PF00106", "Short chain dehydrogenase", "Pfam"),
    ("PF08659", "KR domain", "Pfam"),
    ("PF00067", "Cytochrome P450", "Pfam"),
    ("PF13561", "Enoyl-CoA hydratase/isomerase", "Pfam"),
    ("PF00005", "ABC transporter", "Pfam"),
    ("PF00072", "Response regulator receiver domain", "Pfam"),
    ("PF00440", "Bacterial regulatory proteins tetR", "Pfam"),
]

_BIOME_LINEAGES = [
    "root.Environmental.Terrestrial.Soil",
    "root.Environmental.Aquatic.Marine",
    "root.Environmental.Aquatic.Freshwater",
    "root.Host_associated.Human.Digestive_system",
    "root.Host_associated.Plants.Rhizosphere",
    "root.Environmental.Terrestrial.Volcanic",
    "root.Host_associated.Insecta",
]

_AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"
_NT_ALPHABET = "ACGT"

_GENE_CALLERS = ["Prodigal", "Pyrodigal", "MetaProdigal"]


def _random_aa(length: int) -> str:
    return "".join(random.choices(_AA_ALPHABET, k=length))


def _random_nt(length: int) -> str:
    return "".join(random.choices(_NT_ALPHABET, k=length))


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _clustered_umap(bgc_class: str, jitter: float = 2.0):
    cx, cy = _UMAP_CENTERS.get(bgc_class, (0.0, 0.0))
    return round(cx + random.gauss(0, jitter), 4), round(cy + random.gauss(0, jitter), 4)


def _build_taxonomy_path(tax: tuple) -> str:
    """Build a dot-delimited ltree path from taxonomy tuple (kingdom→genus)."""
    parts = [t for t in tax[:6] if t]
    return ".".join(parts) if parts else ""


def _build_classification_path(l1: str, l2: str = None, l3: str = None) -> str:
    parts = [p.replace(".", "_").replace(" ", "_") for p in [l1, l2, l3] if p]
    return ".".join(parts) if parts else ""


def _morgan_fp_bytes(smiles: str) -> bytes:
    """Try to compute a Morgan fingerprint; return empty bytes on failure."""
    try:
        from rdkit import Chem
        from rdkit.Chem import rdFingerprintGenerator
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return b""
        mfpgen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
        fp = mfpgen.GetFingerprint(mol)
        return fp.ToBitString().encode("ascii")
    except Exception:
        return b""


def _svg_placeholder() -> str:
    """Tiny base64-encoded SVG circle as a placeholder structure thumbnail."""
    import base64
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="28" fill="#ddd" stroke="#999"/></svg>'
    return base64.b64encode(svg.encode()).decode()


class Command(BaseCommand):
    help = "Seed ALL discovery models with realistic mock data"

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Delete all discovery data first")
        parser.add_argument("--small", action="store_true", help="Create a smaller dataset (20 assemblies)")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write("Clearing discovery tables...")
            # Delete in FK-safe order
            for model in [
                RegionAccessionAlias,
                CdsSequence, BgcDomain, DashboardCds,
                BgcEmbedding, ProteinEmbedding,
                NaturalProductChemOntClass,
                DashboardNaturalProduct,
                DashboardBgc,
                DashboardRegion,
                ContigSequence, DashboardContig,
                DashboardGCF, DashboardAssembly,
                DashboardBgcClass, DashboardDomain, PrecomputedStats,
                DashboardDetector,
                AssemblySource,
            ]:
                model.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Cleared."))

        n_assemblies = 20 if options["small"] else 80
        self.stdout.write(f"Seeding {n_assemblies} assemblies...")

        # ── 0. AssemblySource (lookup table) ──────────────────────────────
        _SOURCES = ["MGnify", "GTDB", "NCBI", "MIBiG"]
        source_objs = {}
        for name in _SOURCES:
            obj, _ = AssemblySource.objects.get_or_create(name=name)
            source_objs[name] = obj

        # ── 1. DashboardAssembly ──────────────────────────────────────────
        assemblies = []
        for i in range(n_assemblies):
            tax = random.choice(_TAXONOMY_POOL)
            is_ts = random.random() < 0.12
            gsm = round(random.uniform(2.5, 12.0), 2)

            diversity = round(random.betavariate(3, 3), 4)
            novelty = round(random.betavariate(2, 5), 4)
            density = round(random.uniform(0.0, 1.0), 4)

            # Weighted random: 60% genome, 30% metagenome, 10% region
            _type_roll = random.random()
            if _type_roll < 0.6:
                atype = AssemblyType.GENOME
            elif _type_roll < 0.9:
                atype = AssemblyType.METAGENOME
            else:
                atype = AssemblyType.REGION

            asm = DashboardAssembly(
                assembly_accession=f"DISC_ERZ{i:07d}",
                organism_name=f"{tax[6]} strain {chr(65 + i % 26)}{i}",
                source=source_objs[random.choice(["MGnify", "GTDB", "NCBI"])],
                assembly_type=atype,
                biome_path=random.choice(_BIOME_LINEAGES),
                is_type_strain=is_ts,
                type_strain_catalog_url=(
                    f"https://www.dsmz.de/collection/catalogue/details/culture/DSM-{random.randint(1000, 99999)}"
                    if is_ts else ""
                ),
                url=f"https://www.ncbi.nlm.nih.gov/datasets/genome/DISC_ERZ{i:07d}/",
                assembly_size_mb=gsm,
                bgc_diversity_score=diversity,
                bgc_novelty_score=novelty,
                bgc_density=density,
                taxonomic_novelty=round(random.betavariate(2, 4), 4),
            )
            asm._tax = tax  # stash for contig taxonomy assignment
            assemblies.append(asm)

        DashboardAssembly.objects.bulk_create(assemblies)
        self.stdout.write(f"  {len(assemblies)} DashboardAssembly rows.")

        # ── 2. GCF family paths (assigned to BGCs, table rebuilt later) ──
        n_gcfs = max(5, n_assemblies // 4)
        gcf_family_paths = [f"GCF_{gi:06d}" for gi in range(n_gcfs)]
        self.stdout.write(f"  {n_gcfs} GCF family paths prepared.")

        # ── 2.5. DashboardContig + ContigSequence ──────────────────────
        self.stdout.write("Creating contigs with sequences...")
        all_contigs = []
        contig_seqs = []
        contig_map = {}  # (assembly_accession, contig_idx) -> DashboardContig
        contig_counter = 0

        for assembly in assemblies:
            n_contigs = 3  # enough for bi // 4 grouping (up to 12 BGCs -> indices 0,1,2)
            base_tax = assembly._tax
            for ci in range(n_contigs):
                # For metagenomes, mix taxonomies across contigs
                if assembly.assembly_type == AssemblyType.METAGENOME and ci > 0:
                    contig_tax = random.choice(_TAXONOMY_POOL)
                else:
                    contig_tax = base_tax

                contig_acc = f"contig_{assembly.assembly_accession}_{ci}"
                seq_len = random.randint(500000, 1000000)
                raw_seq = _random_nt(seq_len)
                contig = DashboardContig(
                    assembly=assembly,
                    accession=contig_acc,
                    length=seq_len,
                    taxonomy_path=_build_taxonomy_path(contig_tax),
                    source_contig_id=70000 + contig_counter,
                    sequence_sha256=hashlib.sha256(f"contig_{assembly.assembly_accession}_{ci}".encode()).hexdigest(),
                )
                all_contigs.append(contig)
                contig_map[(assembly.assembly_accession, ci)] = (contig, raw_seq)
                contig_counter += 1

        DashboardContig.objects.bulk_create(all_contigs)

        for contig, raw_seq in contig_map.values():
            contig_seqs.append(ContigSequence(
                contig=contig,
                data=ContigSequence.compress_sequence(raw_seq),
            ))
        ContigSequence.objects.bulk_create(contig_seqs)

        self.stdout.write(
            f"  {len(all_contigs)} DashboardContig rows, "
            f"{len(contig_seqs)} ContigSequence rows."
        )

        # ── 2.8. DashboardDetector ────────────────────────────────────
        self.stdout.write("Creating detectors...")
        # version_sort_key: major*1_000_000 + minor*1_000 + patch
        _SEED_DETECTORS = [
            ("antiSMASH v7.1", "antiSMASH", "7.1.0", "ANT", 7_001_000),
            ("antiSMASH v6.0", "antiSMASH", "6.0.0", "ANT", 6_000_000),
            ("GECCO v0.9.8", "GECCO", "0.9.8", "GEC", 9_008),
            ("SanntiS v0.1.0", "SanntiS", "0.1.0", "SAN", 1_000),
        ]
        detector_objs = {}
        for name, tool, version, code, sort_key in _SEED_DETECTORS:
            det = DashboardDetector.objects.create(
                name=name, tool=tool, version=version,
                tool_name_code=code, version_sort_key=sort_key,
            )
            detector_objs[name] = det
        self.stdout.write(f"  {len(detector_objs)} DashboardDetector rows.")

        # ── 3. DashboardBgc ─────────────────────────────────────────────
        self.stdout.write("Creating BGCs with region assignment...")
        all_bgcs = []
        bgc_counter = 0
        assigner = RegionAssigner()

        # Detector pool (weighted: mostly latest antiSMASH, some GECCO/SanntiS)
        _det_pool = [
            ("antiSMASH v7.1", 0.50),
            ("antiSMASH v6.0", 0.15),
            ("GECCO v0.9.8", 0.20),
            ("SanntiS v0.1.0", 0.15),
        ]
        _det_names = [d[0] for d in _det_pool]
        _det_weights = [d[1] for d in _det_pool]

        for assembly in assemblies:
            n_bgcs = random.randint(3, 12)
            for bi in range(n_bgcs):
                bgc_class = random.choice(_BGC_L1_CLASSES)
                ux, uy = _clustered_umap(bgc_class)

                l2, l3 = None, None
                if bgc_class in _NP_CLASSES:
                    l2 = random.choice(list(_NP_CLASSES[bgc_class].keys()))
                    l3 = random.choice(_NP_CLASSES[bgc_class][l2])

                bgc_size = random.randint(5000, 80000)
                start = random.randint(1000, 400000)
                nearest_dist = round(random.uniform(0.1, 1.0), 4)
                nearest_acc = ""
                if nearest_dist < 0.6:
                    nearest_acc = f"BGC{random.randint(1, len(_MIBIG_COMPOUNDS)):07d}"

                gcf_path = random.choice(gcf_family_paths)
                contig_idx = bi // 4
                contig_obj, _ = contig_map[(assembly.assembly_accession, contig_idx)]

                # Pick a detector
                det_name = random.choices(_det_names, weights=_det_weights, k=1)[0]
                det = detector_objs[det_name]

                # Assign region and get structured accession
                region_id, bgc_number, accession = assigner.assign(
                    contig_id=contig_obj.id,
                    start=start,
                    end=start + bgc_size,
                    detector_id=det.id,
                    tool_code=det.tool_name_code,
                )

                # Create each BGC immediately so RegionAssigner merges
                # can redirect region references via UPDATE queries.
                bgc_obj = DashboardBgc.objects.create(
                    assembly=assembly,
                    contig=contig_obj,
                    bgc_accession=accession,
                    start_position=start,
                    end_position=start + bgc_size,
                    classification_path=_build_classification_path(bgc_class, l2, l3),
                    novelty_score=round(random.betavariate(2, 5), 4),
                    domain_novelty=round(random.betavariate(2, 6), 4),
                    size_kb=round(bgc_size / 1000.0, 2),
                    nearest_validated_accession=nearest_acc,
                    nearest_validated_distance=nearest_dist,
                    is_partial=random.random() < 0.2,
                    is_validated=random.random() < 0.03,
                    umap_x=ux,
                    umap_y=uy,
                    gene_cluster_family=gcf_path,
                    detector=det,
                    region_id=region_id,
                    bgc_number=bgc_number,
                )
                all_bgcs.append(bgc_obj)
                bgc_counter += 1

        self.stdout.write(f"  {len(all_bgcs)} DashboardBgc rows.")
        self.stdout.write(f"  {DashboardRegion.objects.count()} DashboardRegion rows.")

        # Update assembly bgc_count and l1_class_count
        for assembly in assemblies:
            bgcs = [b for b in all_bgcs if b.assembly_id == assembly.id]
            assembly.bgc_count = len(bgcs)
            assembly.l1_class_count = len({b.classification_path.split(".")[0] for b in bgcs if b.classification_path})
        DashboardAssembly.objects.bulk_update(assemblies, ["bgc_count", "l1_class_count"])

        # GCF table will be rebuilt after all BGCs are created (step 9.5)

        # ── 4. DashboardCds + BgcDomain (CDS with domain hits) ─────────
        self.stdout.write("Creating CDS and domain architecture...")
        all_cds = []
        all_domains = []
        protein_counter = 0

        for bgc in all_bgcs:
            bgc_length = bgc.end_position - bgc.start_position
            n_cds = random.randint(2, min(8, max(2, bgc_length // 5000)))
            slot_size = bgc_length // n_cds

            for ci in range(n_cds):
                slot_start = bgc.start_position + ci * slot_size
                gene_len = min(random.randint(300, 1200), slot_size - 50)
                gene_len = max(gene_len, 150)
                margin = max(11, slot_size - gene_len - 10)
                cds_start = slot_start + random.randint(10, margin)
                cds_end = min(cds_start + gene_len, bgc.end_position)
                cds_start = max(cds_start, bgc.start_position)

                aa_len = gene_len // 3
                aa_seq = _random_aa(aa_len)
                strand = random.choice([1, -1])
                protein_id_str = f"DISC_MGYP{protein_counter:012d}"
                cluster_rep = (
                    f"MGYP{random.randint(1, 999999):012d}"
                    if random.random() < 0.3 else ""
                )

                cds = DashboardCds(
                    bgc=bgc,
                    protein_id_str=protein_id_str,
                    start_position=cds_start,
                    end_position=cds_end,
                    strand=strand,
                    protein_length=aa_len,
                    gene_caller=random.choice(_GENE_CALLERS),
                    cluster_representative=cluster_rep,
                    protein_sha256=_sha256(aa_seq),
                )
                cds._aa_seq = aa_seq  # stash for CdsSequence creation
                all_cds.append(cds)

                # Domains on this CDS
                n_doms = random.randint(1, 3)
                chosen_doms = random.sample(
                    _PFAM_DOMAIN_POOL, min(n_doms, len(_PFAM_DOMAIN_POOL))
                )
                prot_pos = 0
                for acc, name, ref_db in chosen_doms:
                    dom_len = random.randint(20, min(80, max(20, aa_len - prot_pos - 5)))
                    all_domains.append(BgcDomain(
                        bgc=bgc,
                        cds=cds,  # FK set after CDS bulk_create
                        domain_acc=acc,
                        domain_name=name,
                        domain_description=f"{name} domain",
                        ref_db=ref_db,
                        start_position=prot_pos,
                        end_position=prot_pos + dom_len,
                        score=round(random.uniform(10.0, 300.0), 1),
                        url=f"https://www.ebi.ac.uk/interpro/entry/pfam/{acc}/",
                    ))
                    prot_pos += dom_len + random.randint(5, 30)

                protein_counter += 1

        # Bulk create CDS first (to get IDs)
        DashboardCds.objects.bulk_create(all_cds)

        # Create CdsSequence rows (zlib-compressed amino acid sequences)
        all_cds_seqs = [
            CdsSequence(
                cds=cds,
                data=CdsSequence.compress_sequence(cds._aa_seq),
            )
            for cds in all_cds
        ]
        CdsSequence.objects.bulk_create(all_cds_seqs)

        # Fix domain FK references to the created CDS objects
        for dom in all_domains:
            dom.cds = dom.cds  # already points to the right object after bulk_create
        BgcDomain.objects.bulk_create(all_domains, ignore_conflicts=True)
        self.stdout.write(
            f"  {len(all_cds)} DashboardCds rows, "
            f"{len(all_cds_seqs)} CdsSequence rows, "
            f"{len(all_domains)} BgcDomain rows."
        )

        # ── 5. BgcEmbedding (halfvec) ──────────────────────────────────
        self.stdout.write("Creating BGC embeddings...")
        bgc_embeddings = [
            BgcEmbedding(
                bgc=bgc,
                vector=np.random.randn(1152).astype(np.float32).tolist(),
            )
            for bgc in all_bgcs
        ]
        BgcEmbedding.objects.bulk_create(bgc_embeddings)
        self.stdout.write(f"  {len(bgc_embeddings)} BgcEmbedding rows.")

        # ── 6. ProteinEmbedding (halfvec) ──────────────────────────────
        self.stdout.write("Creating protein embeddings...")
        # Create one embedding per unique protein (dedup by protein_id_str)
        seen_proteins = set()
        prot_embeddings = []
        for i, cds in enumerate(all_cds):
            if cds.protein_id_str in seen_proteins:
                continue
            seen_proteins.add(cds.protein_id_str)
            prot_embeddings.append(ProteinEmbedding(
                source_protein_id=40000 + i,
                protein_sha256=_sha256(cds._aa_seq),
                vector=np.random.randn(1152).astype(np.float32).tolist(),
            ))
        ProteinEmbedding.objects.bulk_create(prot_embeddings)
        self.stdout.write(f"  {len(prot_embeddings)} ProteinEmbedding rows.")

        # ── 7. DashboardNaturalProduct (with morgan_fp + SVG) ──────────
        self.stdout.write("Creating NaturalProducts...")
        svg_placeholder = _svg_placeholder()
        nps = []
        sampled = random.sample(all_bgcs, min(len(all_bgcs) // 3, len(all_bgcs)))
        for bgc in sampled:
            l1 = bgc.classification_path.split(".")[0] if bgc.classification_path else ""
            if l1 not in _NP_CLASSES:
                l1 = random.choice(list(_NP_CLASSES.keys()))
            l2 = random.choice(list(_NP_CLASSES[l1].keys()))
            l3 = random.choice(_NP_CLASSES[l1][l2])
            smiles = random.choice(_SMILES_POOL)
            nps.append(DashboardNaturalProduct(
                bgc=bgc,
                name=f"compound_{bgc.id}",
                smiles=smiles,
                np_class_path=_build_classification_path(l1, l2, l3),
                structure_svg_base64=svg_placeholder,
                morgan_fp=_morgan_fp_bytes(smiles) or None,
            ))
        DashboardNaturalProduct.objects.bulk_create(nps)
        self.stdout.write(f"  {len(nps)} DashboardNaturalProduct rows.")

        # ── 7b. NaturalProductChemOntClass ────────────────────────────
        # For each NP, pick 1–2 ontology lineages and annotate every node
        # along each path so the hierarchy builder produces realistic trees.
        self.stdout.write("Creating ChemOnt classifications...")
        chemont_rows = []
        for np_obj in nps:
            bgc_class = np_obj.bgc.classification_path.split(".")[0] if np_obj.bgc.classification_path else ""
            lineages = _CHEMONT_LINEAGES.get(bgc_class, _CHEMONT_LINEAGES["Polyketide"])
            n_lineages = random.randint(1, min(2, len(lineages)))
            seen_ids: set[str] = set()
            for lineage in random.sample(lineages, n_lineages):
                for chemont_id, chemont_name, base_prob in lineage:
                    if chemont_id in seen_ids:
                        continue  # shared ancestor across lineages
                    seen_ids.add(chemont_id)
                    chemont_rows.append(NaturalProductChemOntClass(
                        natural_product=np_obj,
                        chemont_id=chemont_id,
                        chemont_name=chemont_name,
                        probability=round(max(0.1, min(1.0, base_prob + random.uniform(-0.08, 0.04))), 3),
                    ))
        NaturalProductChemOntClass.objects.bulk_create(chemont_rows, ignore_conflicts=True)
        self.stdout.write(f"  {len(chemont_rows)} NaturalProductChemOntClass rows.")

        # ── 8. Validated (MIBiG) BGCs ─────────────────────────────────
        self.stdout.write("Creating validated (MIBiG) BGCs...")
        # Create MIBiG contigs first (one per compound for simplicity)
        mibig_assembly = assemblies[0]  # attach to first assembly for simplicity
        mibig_contigs = []
        mibig_contig_seqs_data = []
        for i, (compound, _) in enumerate(_MIBIG_COMPOUNDS):
            contig_acc = f"mibig_contig_{i}"
            seq_len = random.randint(100000, 500000)
            raw_seq = _random_nt(seq_len)
            contig = DashboardContig(
                assembly=mibig_assembly,
                accession=contig_acc,
                length=seq_len,
                taxonomy_path=_build_taxonomy_path(random.choice(_TAXONOMY_POOL)),
                source_contig_id=80000 + i,
                sequence_sha256=hashlib.sha256(f"mibig_contig_{i}".encode()).hexdigest(),
            )
            mibig_contigs.append(contig)
            mibig_contig_seqs_data.append(raw_seq)
        DashboardContig.objects.bulk_create(mibig_contigs)
        ContigSequence.objects.bulk_create([
            ContigSequence(
                contig=contig,
                data=ContigSequence.compress_sequence(raw_seq),
            )
            for contig, raw_seq in zip(mibig_contigs, mibig_contig_seqs_data)
        ])

        # Create MIBiG detector
        mibig_det = DashboardDetector.objects.create(
            name="MIBiG v3.1", tool="MIBiG", version="3.1.0",
            tool_name_code="MIB", version_sort_key=3_001_000,
        )

        # Create MIBiG BGC entries with contigs linked
        mibig_bgcs = []
        for i, (compound, bgc_class) in enumerate(_MIBIG_COMPOUNDS):
            ux, uy = _clustered_umap(bgc_class, jitter=1.5)
            bgc_size = random.randint(10000, 80000)
            start = random.randint(1000, 50000)

            region_id, bgc_number, accession = assigner.assign(
                contig_id=mibig_contigs[i].id,
                start=start,
                end=start + bgc_size,
                detector_id=mibig_det.id,
                tool_code=mibig_det.tool_name_code,
            )

            mibig_bgcs.append(DashboardBgc(
                assembly=mibig_assembly,
                contig=mibig_contigs[i],
                bgc_accession=accession,
                start_position=start,
                end_position=start + bgc_size,
                classification_path=_build_classification_path(bgc_class),
                novelty_score=0.0,
                domain_novelty=0.0,
                size_kb=round(bgc_size / 1000.0, 2),
                is_validated=True,
                umap_x=ux,
                umap_y=uy,
                gene_cluster_family=f"MIBiG.{bgc_class}",
                detector=mibig_det,
                region_id=region_id,
                bgc_number=bgc_number,
            ))
        DashboardBgc.objects.bulk_create(mibig_bgcs)

        # Create CDS + CdsSequence for MIBiG BGCs
        mibig_cds_list = []
        for bgc in mibig_bgcs:
            bgc_length = bgc.end_position - bgc.start_position
            n_cds = random.randint(3, 8)
            slot_size = bgc_length // n_cds
            for ci in range(n_cds):
                slot_start = bgc.start_position + ci * slot_size
                gene_len = min(random.randint(300, 1200), slot_size - 50)
                gene_len = max(gene_len, 150)
                margin = max(11, slot_size - gene_len - 10)
                cds_start = slot_start + random.randint(10, margin)
                cds_end = min(cds_start + gene_len, bgc.end_position)
                cds_start = max(cds_start, bgc.start_position)
                aa_len = gene_len // 3
                aa_seq = _random_aa(aa_len)

                cds = DashboardCds(
                    bgc=bgc,
                    protein_id_str=f"MIBIG_PROT_{bgc.id}_{ci}",
                    start_position=cds_start,
                    end_position=cds_end,
                    strand=random.choice([1, -1]),
                    protein_length=aa_len,
                    gene_caller="Prodigal",
                    cluster_representative="",
                    protein_sha256=_sha256(aa_seq),
                )
                cds._aa_seq = aa_seq
                mibig_cds_list.append(cds)

        DashboardCds.objects.bulk_create(mibig_cds_list)
        CdsSequence.objects.bulk_create([
            CdsSequence(
                cds=cds,
                data=CdsSequence.compress_sequence(cds._aa_seq),
            )
            for cds in mibig_cds_list
        ])

        # Create embeddings for MIBiG BGCs
        mibig_embs = [
            BgcEmbedding(
                bgc=bgc,
                vector=np.random.randn(1152).astype(np.float32).tolist(),
            )
            for bgc in mibig_bgcs
        ]
        BgcEmbedding.objects.bulk_create(mibig_embs)

        self.stdout.write(
            f"  {len(mibig_bgcs)} MIBiG DashboardBgc rows (is_validated=True), "
            f"{len(mibig_cds_list)} MIBiG CDS rows."
        )

        # ── 9. DashboardBgcClass + DashboardDomain (precomputed counts)
        self.stdout.write("Creating catalog tables...")
        bgc_class_objs = []
        for class_name in _BGC_L1_CLASSES:
            count = DashboardBgc.objects.filter(classification_path__startswith=class_name).count()
            bgc_class_objs.append(DashboardBgcClass(name=class_name, bgc_count=count))
        DashboardBgcClass.objects.bulk_create(bgc_class_objs)

        domain_objs = []
        for acc, name, ref_db in _PFAM_DOMAIN_POOL:
            count = BgcDomain.objects.filter(domain_acc=acc).values("bgc").distinct().count()
            domain_objs.append(DashboardDomain(
                acc=acc, name=name, ref_db=ref_db,
                description=f"{name} domain", bgc_count=count,
            ))
        DashboardDomain.objects.bulk_create(domain_objs)
        self.stdout.write(
            f"  {len(bgc_class_objs)} DashboardBgcClass, "
            f"{len(domain_objs)} DashboardDomain rows."
        )

        # ── 9.5. Rebuild GCF table from gene_cluster_family ───────────
        self.stdout.write("Rebuilding GCF table from gene_cluster_family...")
        from discovery.services.scores import _rebuild_gcf_table
        _rebuild_gcf_table()
        gcf_count = DashboardGCF.objects.count()
        self.stdout.write(f"  {gcf_count} DashboardGCF rows.")

        # ── 10. Percentile ranks (SQL window functions) ─────────────────
        self.stdout.write("Computing percentile ranks...")
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE discovery_assembly SET
                    pctl_diversity = sub.pctl_d,
                    pctl_novelty = sub.pctl_n,
                    pctl_density = sub.pctl_den
                FROM (
                    SELECT id,
                        PERCENT_RANK() OVER (ORDER BY bgc_diversity_score) * 100 AS pctl_d,
                        PERCENT_RANK() OVER (ORDER BY bgc_novelty_score) * 100 AS pctl_n,
                        PERCENT_RANK() OVER (ORDER BY bgc_density) * 100 AS pctl_den
                    FROM discovery_assembly
                ) sub
                WHERE discovery_assembly.id = sub.id
            """)
        self.stdout.write("  Percentile ranks computed.")

        # ── 11. PrecomputedStats ────────────────────────────────────────
        self.stdout.write("Computing precomputed stats...")
        from discovery.services.stats import compute_assembly_stats, compute_bgc_stats

        assembly_qs = DashboardAssembly.objects.all()
        bgc_qs = DashboardBgc.objects.all()

        assembly_stats = compute_assembly_stats(assembly_qs)
        bgc_stats = compute_bgc_stats(bgc_qs)

        # Enrich bgc_global with sparse_threshold
        all_dists = list(
            DashboardBgc.objects.filter(nearest_validated_distance__isnull=False)
            .values_list("nearest_validated_distance", flat=True)[:10000]
        )
        sparse_threshold = float(np.percentile(all_dists, 75)) if all_dists else 0.5
        bgc_stats["sparse_threshold"] = sparse_threshold

        # Enrich assembly_global with radar references
        radar_refs = []
        for dim, label in [
            ("bgc_diversity_score", "Diversity"),
            ("bgc_novelty_score", "Novelty"),
            ("bgc_density", "Density"),
        ]:
            from django.db.models import Avg
            agg = DashboardAssembly.objects.aggregate(db_mean=Avg(dim))
            vals = list(DashboardAssembly.objects.values_list(dim, flat=True)[:10000])
            db_p90 = float(np.percentile(vals, 90)) if vals else 0.0
            radar_refs.append({
                "dimension": dim,
                "label": label,
                "db_mean": round(agg["db_mean"] or 0.0, 4),
                "db_p90": round(db_p90, 4),
            })
        assembly_stats["radar_references"] = radar_refs

        PrecomputedStats.objects.update_or_create(
            key="assembly_global", defaults={"data": assembly_stats},
        )
        PrecomputedStats.objects.update_or_create(
            key="bgc_global", defaults={"data": bgc_stats},
        )
        self.stdout.write("  PrecomputedStats written.")

        # ── Summary ─────────────────────────────────────────────────────
        total_bgcs = len(all_bgcs) + len(mibig_bgcs)
        total_cds = len(all_cds) + len(mibig_cds_list)
        total_contigs = len(all_contigs) + len(mibig_contigs)
        self.stdout.write(self.style.SUCCESS(
            f"\nDone! Seeded all discovery tables:\n"
            f"  DashboardAssembly:        {len(assemblies)}\n"
            f"  DashboardContig:          {total_contigs}\n"
            f"  ContigSequence:           {total_contigs}\n"
            f"  DashboardBgc:             {total_bgcs} ({len(mibig_bgcs)} validated/MIBiG)\n"
            f"  DashboardCds:             {total_cds}\n"
            f"  CdsSequence:              {total_cds}\n"
            f"  BgcDomain:                {len(all_domains)}\n"
            f"  BgcEmbedding:             {len(bgc_embeddings) + len(mibig_embs)}\n"
            f"  ProteinEmbedding:         {len(prot_embeddings)}\n"
            f"  DashboardGCF:             {gcf_count}\n"
            f"  DashboardNaturalProduct:  {len(nps)}\n"
            f"  NaturalProductChemOntClass: {len(chemont_rows)}\n"
            f"  DashboardBgcClass:        {len(bgc_class_objs)}\n"
            f"  DashboardDomain:          {len(domain_objs)}\n"
            f"  PrecomputedStats:         2"
        ))
