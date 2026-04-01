"""
Seed the discovery app with realistic mock data for dashboard development.

Seeds the self-contained discovery models (DashboardGenome, DashboardBgc, etc.)
without requiring data in the mgnify_bgcs core tables.

Usage:
    python manage.py seed_discovery_data
    python manage.py seed_discovery_data --clear   # wipe discovery tables first
    python manage.py seed_discovery_data --small    # smaller dataset (20 genomes)
"""

import math
import random

import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction

from discovery.models import (
    BgcDomain,
    BgcEmbedding,
    DashboardBgc,
    DashboardBgcClass,
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


def _clustered_umap(bgc_class: str, jitter: float = 2.0):
    cx, cy = _UMAP_CENTERS.get(bgc_class, (0.0, 0.0))
    return round(cx + random.gauss(0, jitter), 4), round(cy + random.gauss(0, jitter), 4)


def _build_taxonomy_path(tax: tuple) -> str:
    """Build a dot-delimited ltree path from taxonomy tuple."""
    parts = [t for t in tax[:6] if t]  # exclude species from path
    return ".".join(parts) if parts else ""


def _build_classification_path(l1: str, l2: str = None, l3: str = None) -> str:
    parts = [p.replace(".", "_").replace(" ", "_") for p in [l1, l2, l3] if p]
    return ".".join(parts) if parts else ""


class Command(BaseCommand):
    help = "Seed discovery models with realistic mock data"

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Delete all discovery data first")
        parser.add_argument("--small", action="store_true", help="Create a smaller dataset (20 genomes)")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write("Clearing discovery tables...")
            for model in [
                BgcDomain, BgcEmbedding, ProteinEmbedding,
                DashboardNaturalProduct, DashboardMibigReference,
                DashboardBgc, DashboardGCF, DashboardGenome,
                DashboardBgcClass, DashboardDomain, PrecomputedStats,
            ]:
                model.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Cleared."))

        n_genomes = 20 if options["small"] else 80
        self.stdout.write(f"Seeding {n_genomes} genomes...")

        # 1. Create DashboardGenomes
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

            genome = DashboardGenome(
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
            )
            genomes.append(genome)

        DashboardGenome.objects.bulk_create(genomes)
        self.stdout.write(f"  {len(genomes)} genomes created.")

        # 2. Create DashboardGCFs
        n_gcfs = max(5, n_genomes // 4)
        gcf_list = []
        for gi in range(n_gcfs):
            gcf = DashboardGCF(
                family_id=f"GCF_{gi:06d}",
                member_count=0,
                known_chemistry_annotation="" if random.random() > 0.3 else random.choice(_MIBIG_COMPOUNDS)[0],
                mibig_accession="" if random.random() > 0.3 else f"BGC{gi + 1:07d}",
                mean_novelty=round(random.uniform(0.1, 0.8), 4),
            )
            gcf_list.append(gcf)
        DashboardGCF.objects.bulk_create(gcf_list)
        # Refresh to get IDs
        gcf_list = list(DashboardGCF.objects.all())
        self.stdout.write(f"  {len(gcf_list)} GCFs created.")

        # 3. Create DashboardBgcs
        all_bgcs = []
        genome_bgc_counts: dict[int, int] = {}

        for genome in genomes:
            n_bgcs = random.randint(3, 12)
            genome_bgc_counts[genome.id] = n_bgcs

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

                bgc = DashboardBgc(
                    genome=genome,
                    bgc_accession=f"MGYB{10000 + len(all_bgcs):012d}",
                    contig_accession=f"contig_{genome.source_assembly_id}_{bi}",
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
                    umap_x=ux,
                    umap_y=uy,
                    gcf_id=gcf.id,
                    distance_to_gcf_representative=round(random.uniform(0.0, 0.5), 4),
                    detector_names="antiSMASH",
                    source_bgc_id=20000 + len(all_bgcs),
                    source_contig_id=30000 + len(all_bgcs),
                )
                all_bgcs.append(bgc)

        DashboardBgc.objects.bulk_create(all_bgcs)
        self.stdout.write(f"  {len(all_bgcs)} BGCs created.")

        # Update genome bgc_count and l1_class_count
        for genome in genomes:
            bgcs = [b for b in all_bgcs if b.genome_id == genome.id]
            genome.bgc_count = len(bgcs)
            class_set = {b.classification_l1 for b in bgcs if b.classification_l1}
            genome.l1_class_count = len(class_set)
        DashboardGenome.objects.bulk_update(genomes, ["bgc_count", "l1_class_count"])

        # Update GCF member counts
        for gcf in gcf_list:
            gcf.member_count = DashboardBgc.objects.filter(gcf_id=gcf.id).count()
        DashboardGCF.objects.bulk_update(gcf_list, ["member_count"])

        # Set representative BGC for each GCF
        for gcf in gcf_list:
            rep = DashboardBgc.objects.filter(gcf_id=gcf.id).order_by("distance_to_gcf_representative").first()
            if rep:
                gcf.representative_bgc = rep
        DashboardGCF.objects.bulk_update(gcf_list, ["representative_bgc"])

        # 4. Create BgcEmbeddings (halfvec)
        self.stdout.write("Creating BGC embeddings...")
        embeddings = [
            BgcEmbedding(
                bgc=bgc,
                vector=np.random.randn(1152).astype(np.float32).tolist(),
            )
            for bgc in all_bgcs
        ]
        BgcEmbedding.objects.bulk_create(embeddings)
        self.stdout.write(f"  {len(embeddings)} BGC embeddings created.")

        # 5. Create BgcDomains (denormalized)
        self.stdout.write("Creating BGC domain associations...")
        domain_associations = []
        for bgc in all_bgcs:
            n_domains = random.randint(2, 6)
            chosen = random.sample(_PFAM_DOMAIN_POOL, min(n_domains, len(_PFAM_DOMAIN_POOL)))
            for acc, name, ref_db in chosen:
                domain_associations.append(
                    BgcDomain(
                        bgc=bgc,
                        domain_acc=acc,
                        domain_name=name,
                        domain_description=f"{name} domain",
                        ref_db=ref_db,
                    )
                )
        BgcDomain.objects.bulk_create(domain_associations, ignore_conflicts=True)
        self.stdout.write(f"  {len(domain_associations)} domain associations created.")

        # 6. Create DashboardNaturalProducts
        self.stdout.write("Creating NaturalProducts...")
        nps = []
        sampled = random.sample(all_bgcs, min(len(all_bgcs) // 3, len(all_bgcs)))
        for bgc in sampled:
            l1 = bgc.classification_l1
            if l1 not in _NP_CLASSES:
                l1 = random.choice(list(_NP_CLASSES.keys()))
            l2 = random.choice(list(_NP_CLASSES[l1].keys()))
            l3 = random.choice(_NP_CLASSES[l1][l2])
            nps.append(
                DashboardNaturalProduct(
                    bgc=bgc,
                    name=f"compound_{bgc.id}",
                    smiles=random.choice(_SMILES_POOL),
                    np_class_path=_build_classification_path(l1, l2, l3),
                    chemical_class_l1=l1,
                    chemical_class_l2=l2,
                    chemical_class_l3=l3,
                    producing_organism=bgc.genome.organism_name if bgc.genome else "",
                )
            )
        DashboardNaturalProduct.objects.bulk_create(nps)
        self.stdout.write(f"  {len(nps)} NaturalProducts created.")

        # 7. Create DashboardMibigReferences
        self.stdout.write("Creating MIBiG references...")
        mibig_refs = []
        for i, (compound, bgc_class) in enumerate(_MIBIG_COMPOUNDS):
            ux, uy = _clustered_umap(bgc_class, jitter=1.5)
            mibig_refs.append(
                DashboardMibigReference(
                    accession=f"BGC{i + 1:07d}",
                    compound_name=compound,
                    bgc_class=bgc_class,
                    umap_x=ux,
                    umap_y=uy,
                    embedding=np.random.randn(1152).astype(np.float32).tolist(),
                )
            )
        DashboardMibigReference.objects.bulk_create(mibig_refs)
        self.stdout.write(f"  {len(mibig_refs)} MIBiG references created.")

        # 8. Create DashboardBgcClass and DashboardDomain (precomputed counts)
        self.stdout.write("Creating catalog tables...")
        for class_name in _BGC_L1_CLASSES:
            count = DashboardBgc.objects.filter(classification_l1=class_name).count()
            DashboardBgcClass.objects.create(name=class_name, bgc_count=count)

        for acc, name, ref_db in _PFAM_DOMAIN_POOL:
            count = BgcDomain.objects.filter(domain_acc=acc).values("bgc").distinct().count()
            DashboardDomain.objects.create(
                acc=acc, name=name, ref_db=ref_db,
                description=f"{name} domain", bgc_count=count,
            )
        self.stdout.write("  Catalog tables populated.")

        # 9. Compute percentile ranks
        self.stdout.write("Computing percentile ranks...")
        from django.db import connection
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

        # 10. Compute PrecomputedStats
        self.stdout.write("Computing precomputed stats...")
        from discovery.services.stats import compute_genome_stats, compute_bgc_stats

        genome_qs = DashboardGenome.objects.all()
        bgc_qs = DashboardBgc.objects.all()

        PrecomputedStats.objects.update_or_create(
            key="genome_global",
            defaults={"data": compute_genome_stats(genome_qs)},
        )
        PrecomputedStats.objects.update_or_create(
            key="bgc_global",
            defaults={"data": compute_bgc_stats(bgc_qs)},
        )

        self.stdout.write(self.style.SUCCESS(
            f"Done! Seeded {n_genomes} genomes, {len(all_bgcs)} BGCs, "
            f"{len(embeddings)} embeddings, {len(domain_associations)} domain associations, "
            f"{len(nps)} NaturalProducts, {len(mibig_refs)} MIBiG refs, "
            f"{len(gcf_list)} GCFs."
        ))
