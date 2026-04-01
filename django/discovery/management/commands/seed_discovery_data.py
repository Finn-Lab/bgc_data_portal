"""
Seed the discovery app with realistic mock data for dashboard development.

Seeds ALL self-contained discovery models with data that exercises every
field, relationship, and dashboard feature.

Usage:
    python manage.py seed_discovery_data
    python manage.py seed_discovery_data --clear   # wipe discovery tables first
    python manage.py seed_discovery_data --small    # smaller dataset (20 genomes)
"""

import hashlib
import math
import random

import numpy as np
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from discovery.models import (
    BgcDomain,
    BgcEmbedding,
    DashboardBgc,
    DashboardBgcClass,
    DashboardCds,
    DashboardDomain,
    DashboardGCF,
    DashboardGenome,
    DashboardMibigReference,
    DashboardNaturalProduct,
    PrecomputedStats,
    ProteinEmbedding,
)


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

_ISOLATION_SOURCES = [
    "soil", "marine sediment", "freshwater", "rhizosphere",
    "human gut", "insect symbiont", "cave sediment", "hot spring",
]

_AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"

_GENE_CALLERS = ["Prodigal", "Pyrodigal", "MetaProdigal"]


def _random_aa(length: int) -> str:
    return "".join(random.choices(_AA_ALPHABET, k=length))


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
        from rdkit.Chem import AllChem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return b""
        fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
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
        parser.add_argument("--small", action="store_true", help="Create a smaller dataset (20 genomes)")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write("Clearing discovery tables...")
            # Delete in FK-safe order
            for model in [
                BgcDomain, DashboardCds, BgcEmbedding, ProteinEmbedding,
                DashboardNaturalProduct, DashboardMibigReference,
                DashboardBgc, DashboardGCF, DashboardGenome,
                DashboardBgcClass, DashboardDomain, PrecomputedStats,
            ]:
                model.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Cleared."))

        n_genomes = 20 if options["small"] else 80
        self.stdout.write(f"Seeding {n_genomes} genomes...")

        # ── 1. DashboardGenome ──────────────────────────────────────────
        genomes = []
        for i in range(n_genomes):
            tax = random.choice(_TAXONOMY_POOL)
            is_ts = random.random() < 0.12
            gq = round(random.betavariate(8, 2), 3)
            gsm = round(random.uniform(2.5, 12.0), 2)

            diversity = round(random.betavariate(3, 3), 4)
            novelty = round(random.betavariate(2, 5), 4)
            density = round(random.uniform(0.0, 1.0), 4)
            composite = round(
                (0.30 * diversity + 0.45 * novelty + 0.25 * density), 4
            )

            genomes.append(DashboardGenome(
                assembly_accession=f"DISC_ERZ{i:07d}",
                organism_name=f"{tax[6]} strain {chr(65 + i % 26)}{i}",
                taxonomy_path=_build_taxonomy_path(tax),
                taxonomy_kingdom=tax[0],
                taxonomy_phylum=tax[1],
                taxonomy_class=tax[2],
                taxonomy_order=tax[3],
                taxonomy_family=tax[4],
                taxonomy_genus=tax[5],
                taxonomy_species=tax[6],
                biome_path=random.choice(_BIOME_LINEAGES),
                is_type_strain=is_ts,
                type_strain_catalog_url=(
                    f"https://www.dsmz.de/collection/catalogue/details/culture/DSM-{random.randint(1000, 99999)}"
                    if is_ts else ""
                ),
                genome_size_mb=gsm,
                genome_quality=gq,
                isolation_source=random.choice(_ISOLATION_SOURCES),
                bgc_diversity_score=diversity,
                bgc_novelty_score=novelty,
                bgc_density=density,
                taxonomic_novelty=round(random.betavariate(2, 4), 4),
                composite_score=composite,
                source_assembly_id=10000 + i,
            ))

        DashboardGenome.objects.bulk_create(genomes)
        self.stdout.write(f"  {len(genomes)} DashboardGenome rows.")

        # ── 2. DashboardGCF ─────────────────────────────────────────────
        n_gcfs = max(5, n_genomes // 4)
        gcf_list = []
        for gi in range(n_gcfs):
            has_mibig = random.random() < 0.3
            gcf_list.append(DashboardGCF(
                family_id=f"GCF_{gi:06d}",
                member_count=0,
                known_chemistry_annotation=(
                    random.choice(_MIBIG_COMPOUNDS)[0] if has_mibig else ""
                ),
                mibig_accession=(
                    f"BGC{gi + 1:07d}" if has_mibig else ""
                ),
                mean_novelty=round(random.uniform(0.1, 0.8), 4),
                mibig_count=1 if has_mibig else 0,
            ))
        DashboardGCF.objects.bulk_create(gcf_list)
        gcf_list = list(DashboardGCF.objects.all())
        self.stdout.write(f"  {len(gcf_list)} DashboardGCF rows.")

        # ── 3. DashboardBgc ─────────────────────────────────────────────
        all_bgcs = []
        bgc_counter = 0

        for genome in genomes:
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

                gcf = random.choice(gcf_list)

                all_bgcs.append(DashboardBgc(
                    genome=genome,
                    bgc_accession=f"MGYB{10000 + bgc_counter:012d}",
                    contig_accession=f"contig_{genome.source_assembly_id}_{bi // 4}",
                    start_position=start,
                    end_position=start + bgc_size,
                    classification_path=_build_classification_path(bgc_class, l2, l3),
                    classification_l1=bgc_class,
                    classification_l2=l2 or "",
                    classification_l3=l3 or "",
                    novelty_score=round(random.betavariate(2, 5), 4),
                    domain_novelty=round(random.betavariate(2, 6), 4),
                    size_kb=round(bgc_size / 1000.0, 2),
                    nearest_mibig_accession=nearest_acc,
                    nearest_mibig_distance=nearest_dist,
                    is_partial=random.random() < 0.2,
                    is_validated=random.random() < 0.03,
                    is_mibig=False,
                    umap_x=ux,
                    umap_y=uy,
                    gcf_id=gcf.id,
                    distance_to_gcf_representative=round(random.uniform(0.0, 0.5), 4),
                    detector_names="antiSMASH",
                    source_bgc_id=20000 + bgc_counter,
                    source_contig_id=30000 + bgc_counter,
                ))
                bgc_counter += 1

        DashboardBgc.objects.bulk_create(all_bgcs)
        self.stdout.write(f"  {len(all_bgcs)} DashboardBgc rows.")

        # Update genome bgc_count and l1_class_count
        for genome in genomes:
            bgcs = [b for b in all_bgcs if b.genome_id == genome.id]
            genome.bgc_count = len(bgcs)
            genome.l1_class_count = len({b.classification_l1 for b in bgcs if b.classification_l1})
        DashboardGenome.objects.bulk_update(genomes, ["bgc_count", "l1_class_count"])

        # Update GCF member counts + representative BGC
        for gcf in gcf_list:
            members = DashboardBgc.objects.filter(gcf_id=gcf.id)
            gcf.member_count = members.count()
            rep = members.order_by("distance_to_gcf_representative").first()
            if rep:
                gcf.representative_bgc = rep
        DashboardGCF.objects.bulk_update(gcf_list, ["member_count", "representative_bgc"])

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
                    sequence=aa_seq,
                )
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
                    ))
                    prot_pos += dom_len + random.randint(5, 30)

                protein_counter += 1

        # Bulk create CDS first (to get IDs)
        DashboardCds.objects.bulk_create(all_cds)
        # Fix domain FK references to the created CDS objects
        for dom in all_domains:
            dom.cds = dom.cds  # already points to the right object after bulk_create
        BgcDomain.objects.bulk_create(all_domains, ignore_conflicts=True)
        self.stdout.write(
            f"  {len(all_cds)} DashboardCds rows, "
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
                protein_sha256=_sha256(cds.sequence),
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
            l1 = bgc.classification_l1
            if l1 not in _NP_CLASSES:
                l1 = random.choice(list(_NP_CLASSES.keys()))
            l2 = random.choice(list(_NP_CLASSES[l1].keys()))
            l3 = random.choice(_NP_CLASSES[l1][l2])
            smiles = random.choice(_SMILES_POOL)
            nps.append(DashboardNaturalProduct(
                bgc=bgc,
                name=f"compound_{bgc.source_bgc_id}",
                smiles=smiles,
                np_class_path=_build_classification_path(l1, l2, l3),
                chemical_class_l1=l1,
                chemical_class_l2=l2,
                chemical_class_l3=l3,
                structure_svg_base64=svg_placeholder,
                producing_organism=(
                    bgc.genome.organism_name if bgc.genome else ""
                ),
                morgan_fp=_morgan_fp_bytes(smiles) or None,
            ))
        DashboardNaturalProduct.objects.bulk_create(nps)
        self.stdout.write(f"  {len(nps)} DashboardNaturalProduct rows.")

        # ── 8. DashboardMibigReference (with dashboard_bgc link) ───────
        self.stdout.write("Creating MIBiG references...")
        # Create MIBiG BGC entries first so we can link them
        mibig_bgcs = []
        mibig_genome = genomes[0]  # attach to first genome for simplicity
        for i, (compound, bgc_class) in enumerate(_MIBIG_COMPOUNDS):
            ux, uy = _clustered_umap(bgc_class, jitter=1.5)
            mibig_bgcs.append(DashboardBgc(
                genome=mibig_genome,
                bgc_accession=f"MIBIG_{compound.upper().replace(' ', '_')[:20]}",
                contig_accession="mibig_contig",
                start_position=i * 100000,
                end_position=i * 100000 + random.randint(10000, 80000),
                classification_path=_build_classification_path(bgc_class),
                classification_l1=bgc_class,
                novelty_score=0.0,
                domain_novelty=0.0,
                size_kb=round(random.uniform(10, 80), 2),
                is_mibig=True,
                umap_x=ux,
                umap_y=uy,
                detector_names="MIBiG",
                source_bgc_id=50000 + i,
                source_contig_id=60000,
            ))
        DashboardBgc.objects.bulk_create(mibig_bgcs)

        mibig_refs = []
        for i, (compound, bgc_class) in enumerate(_MIBIG_COMPOUNDS):
            mibig_refs.append(DashboardMibigReference(
                accession=f"BGC{i + 1:07d}",
                compound_name=compound,
                bgc_class=bgc_class,
                umap_x=mibig_bgcs[i].umap_x,
                umap_y=mibig_bgcs[i].umap_y,
                embedding=np.random.randn(1152).astype(np.float32).tolist(),
                dashboard_bgc=mibig_bgcs[i],
            ))
        DashboardMibigReference.objects.bulk_create(mibig_refs)

        # Create embeddings for MIBiG BGCs too
        mibig_embs = [
            BgcEmbedding(
                bgc=bgc,
                vector=np.random.randn(1152).astype(np.float32).tolist(),
            )
            for bgc in mibig_bgcs
        ]
        BgcEmbedding.objects.bulk_create(mibig_embs)

        self.stdout.write(
            f"  {len(mibig_refs)} DashboardMibigReference rows "
            f"(linked to {len(mibig_bgcs)} MIBiG DashboardBgc rows)."
        )

        # ── 9. DashboardBgcClass + DashboardDomain (precomputed counts)
        self.stdout.write("Creating catalog tables...")
        bgc_class_objs = []
        for class_name in _BGC_L1_CLASSES:
            count = DashboardBgc.objects.filter(classification_l1=class_name).count()
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

        # ── 10. Percentile ranks (SQL window functions) ─────────────────
        self.stdout.write("Computing percentile ranks...")
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE discovery_genome SET
                    pctl_diversity = sub.pctl_d,
                    pctl_novelty = sub.pctl_n,
                    pctl_density = sub.pctl_den
                FROM (
                    SELECT id,
                        PERCENT_RANK() OVER (ORDER BY bgc_diversity_score) * 100 AS pctl_d,
                        PERCENT_RANK() OVER (ORDER BY bgc_novelty_score) * 100 AS pctl_n,
                        PERCENT_RANK() OVER (ORDER BY bgc_density) * 100 AS pctl_den
                    FROM discovery_genome
                ) sub
                WHERE discovery_genome.id = sub.id
            """)
        self.stdout.write("  Percentile ranks computed.")

        # ── 11. PrecomputedStats ────────────────────────────────────────
        self.stdout.write("Computing precomputed stats...")
        from discovery.services.stats import compute_genome_stats, compute_bgc_stats

        genome_qs = DashboardGenome.objects.all()
        bgc_qs = DashboardBgc.objects.all()

        genome_stats = compute_genome_stats(genome_qs)
        bgc_stats = compute_bgc_stats(bgc_qs)

        # Enrich bgc_global with sparse_threshold
        all_dists = list(
            DashboardBgc.objects.filter(nearest_mibig_distance__isnull=False)
            .values_list("nearest_mibig_distance", flat=True)[:10000]
        )
        sparse_threshold = float(np.percentile(all_dists, 75)) if all_dists else 0.5
        bgc_stats["sparse_threshold"] = sparse_threshold

        # Enrich genome_global with radar references
        radar_refs = []
        for dim, label in [
            ("bgc_diversity_score", "Diversity"),
            ("bgc_novelty_score", "Novelty"),
            ("bgc_density", "Density"),
        ]:
            from django.db.models import Avg
            agg = DashboardGenome.objects.aggregate(db_mean=Avg(dim))
            vals = list(DashboardGenome.objects.values_list(dim, flat=True)[:10000])
            db_p90 = float(np.percentile(vals, 90)) if vals else 0.0
            radar_refs.append({
                "dimension": dim,
                "label": label,
                "db_mean": round(agg["db_mean"] or 0.0, 4),
                "db_p90": round(db_p90, 4),
            })
        genome_stats["radar_references"] = radar_refs

        PrecomputedStats.objects.update_or_create(
            key="genome_global", defaults={"data": genome_stats},
        )
        PrecomputedStats.objects.update_or_create(
            key="bgc_global", defaults={"data": bgc_stats},
        )
        self.stdout.write("  PrecomputedStats written.")

        # ── Summary ─────────────────────────────────────────────────────
        total_bgcs = len(all_bgcs) + len(mibig_bgcs)
        self.stdout.write(self.style.SUCCESS(
            f"\nDone! Seeded all 12 discovery tables:\n"
            f"  DashboardGenome:          {len(genomes)}\n"
            f"  DashboardBgc:             {total_bgcs} ({len(mibig_bgcs)} MIBiG)\n"
            f"  DashboardCds:             {len(all_cds)}\n"
            f"  BgcDomain:                {len(all_domains)}\n"
            f"  BgcEmbedding:             {len(bgc_embeddings) + len(mibig_embs)}\n"
            f"  ProteinEmbedding:         {len(prot_embeddings)}\n"
            f"  DashboardGCF:             {len(gcf_list)}\n"
            f"  DashboardNaturalProduct:  {len(nps)}\n"
            f"  DashboardMibigReference:  {len(mibig_refs)}\n"
            f"  DashboardBgcClass:        {len(bgc_class_objs)}\n"
            f"  DashboardDomain:          {len(domain_objs)}\n"
            f"  PrecomputedStats:         2"
        ))
