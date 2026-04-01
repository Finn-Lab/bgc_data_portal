"""
Seed the discovery app with realistic mock data for dashboard development.

Usage:
    python manage.py seed_discovery_data
    python manage.py seed_discovery_data --clear   # wipe discovery tables first
    python manage.py seed_discovery_data --small    # smaller dataset (20 assemblies)
"""

import random
import math

import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction

from mgnify_bgcs.models import (
    Assembly, Bgc, BgcClass, BgcBgcClass, Biome, Cds, Contig,
    Domain, GeneCaller, Protein, ProteinDomain,
)

from discovery.models import (
    GCF,
    GCFMembership,
    NaturalProduct,
    MibigReference,
    GenomeScore,
    BgcScore,
)

# Reuse factory pools for consistency
from tests.factories.models import _TAXONOMY_POOL, _random_aa, _sha256
from tests.factories.discovery_models import (
    _MIBIG_COMPOUNDS,
    _NP_CLASSES,
    _SMILES_POOL,
)


# UMAP cluster centers for 7 BGC classes
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
    ("PF00486", "Transcriptional regulatory protein C-terminal", "Pfam"),
    ("PF00389", "D-alanine-D-alanine ligase", "Pfam"),
    ("PF00465", "Iron-containing alcohol dehydrogenase", "Pfam"),
    ("PF01370", "NAD dependent epimerase", "Pfam"),
    ("PF00535", "Glycosyl transferase family 2", "Pfam"),
]

_BIOME_LINEAGES = [
    "root:Environmental:Terrestrial:Soil",
    "root:Environmental:Aquatic:Marine",
    "root:Environmental:Aquatic:Freshwater",
    "root:Host-associated:Human:Digestive system",
    "root:Host-associated:Plants:Rhizosphere",
    "root:Environmental:Terrestrial:Volcanic",
    "root:Host-associated:Insecta",
]

_ISOLATION_SOURCES = [
    "soil", "marine sediment", "freshwater", "rhizosphere",
    "human gut", "insect symbiont", "cave sediment", "hot spring",
    "mangrove soil", "coral mucus", "desert sand", "peat bog",
]


def _clustered_umap(bgc_class: str, jitter: float = 2.0):
    cx, cy = _UMAP_CENTERS.get(bgc_class, (0.0, 0.0))
    return (
        round(cx + random.gauss(0, jitter), 4),
        round(cy + random.gauss(0, jitter), 4),
    )


class Command(BaseCommand):
    help = "Seed discovery models with realistic mock data"

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Delete all discovery data first")
        parser.add_argument("--small", action="store_true", help="Create a smaller dataset (20 assemblies)")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write("Clearing discovery tables...")
            BgcScore.objects.all().delete()
            GenomeScore.objects.all().delete()
            GCFMembership.objects.all().delete()
            NaturalProduct.objects.all().delete()
            MibigReference.objects.all().delete()
            GCF.objects.all().delete()
            # Clean up seeded domain architecture
            # (Protein cascade-deletes ProteinDomain)
            Protein.objects.filter(
                mgyp__startswith="DISC_MGYP"
            ).delete()
            # Clean up seeded assemblies/contigs/bgcs
            # (Assembly cascades to Contig/CDS/BGC)
            Assembly.objects.filter(
                accession__startswith="DISC_ERZ"
            ).delete()
            self.stdout.write(self.style.SUCCESS("Cleared."))

        n_assemblies = 20 if options["small"] else 80
        self.stdout.write(f"Seeding {n_assemblies} assemblies...")

        # 1. Ensure BGC classes exist
        bgc_class_objs = {}
        for name in _BGC_L1_CLASSES:
            obj, _ = BgcClass.objects.get_or_create(name=name)
            bgc_class_objs[name] = obj

        # 2. Create MIBiG references with full Bgc records
        self.stdout.write("Creating MIBiG references (with full BGC records)...")
        mibig_refs = []

        # Create a dedicated MIBiG assembly and contig
        mibig_assembly, _ = Assembly.objects.get_or_create(
            accession="MIBIG_REFERENCE",
            defaults=dict(
                organism_name="MIBiG Reference Collection",
                is_type_strain=False,
                genome_size_mb=0.0,
                genome_quality=1.0,
            ),
        )
        mibig_contig, _ = Contig.objects.get_or_create(
            sequence_sha256="mibig_reference_contig_sha256",
            defaults=dict(
                assembly=mibig_assembly,
                mgyc="MIBIG_CONTIG",
                accession="mibig_contig",
                name="mibig_contig",
                length=10_000_000,
                sequence="ACGT" * 2_500_000,
            ),
        )
        gene_caller_mibig, _ = GeneCaller.objects.get_or_create(
            name="MIBiG", defaults={"tool": "MIBiG", "version": "3.0"}
        )

        # Ensure domains exist for MIBiG BGCs
        mibig_domain_objs = {}
        for acc, name, ref_db in _PFAM_DOMAIN_POOL:
            obj, _ = Domain.objects.get_or_create(
                acc=acc,
                defaults={"name": name, "ref_db": ref_db, "description": f"{name} domain"},
            )
            mibig_domain_objs[acc] = obj
        mibig_domain_list = list(mibig_domain_objs.values())

        mibig_proteins = []
        mibig_cds_pending = []
        mibig_pds_pending = []
        mibig_protein_idx = 0

        for i, (compound, bgc_class) in enumerate(_MIBIG_COMPOUNDS):
            ux, uy = _clustered_umap(bgc_class, jitter=1.5)
            emb = np.random.randn(1152).astype(np.float32).tolist()

            # Create full Bgc record for MIBiG entry
            bgc_start = i * 100_000
            bgc_end = bgc_start + random.randint(10_000, 80_000)
            mibig_bgc = Bgc.objects.create(
                contig=mibig_contig,
                identifier=f"mibig_BGC{i + 1:07d}",
                start_position=bgc_start,
                end_position=bgc_end,
                is_partial=False,
                is_mibig=True,
                embedding=emb,
                metadata={
                    "umap_x_coord": ux,
                    "umap_y_coord": uy,
                    "detectors": ["MIBiG"],
                },
            )
            BgcBgcClass.objects.get_or_create(
                bgc=mibig_bgc,
                bgc_class=bgc_class_objs.get(bgc_class, bgc_class_objs["Other"]),
            )

            # Create CDS/Protein/ProteinDomain for this MIBiG BGC
            bgc_length = bgc_end - bgc_start
            n_cds = random.randint(3, 6)
            slot_size = bgc_length // n_cds
            for ci in range(n_cds):
                slot_start = bgc_start + ci * slot_size
                gene_len = min(random.randint(300, 900), slot_size - 50)
                gene_len = max(gene_len, 150)
                margin = max(11, slot_size - gene_len - 10)
                cds_start = slot_start + random.randint(10, margin)
                cds_end = min(cds_start + gene_len, bgc_end)
                cds_start = max(cds_start, bgc_start)

                aa_seq = _random_aa(gene_len // 3)
                seq_hash = _sha256(f"mibig_{aa_seq}_{mibig_protein_idx}")

                protein = Protein(
                    sequence=aa_seq,
                    sequence_sha256=seq_hash,
                    mgyp=f"MIBIG_MGYP{mibig_protein_idx:012d}",
                )
                mibig_proteins.append(protein)

                cds = Cds(
                    protein=None,
                    contig=mibig_contig,
                    gene_caller=gene_caller_mibig,
                    start_position=cds_start,
                    end_position=cds_end,
                    strand=random.choice([1, -1]),
                    protein_identifier=f"MIBIG_MGYP{mibig_protein_idx:012d}",
                    pipeline_version="1.0",
                )
                mibig_cds_pending.append((cds, mibig_protein_idx))

                n_domains = random.randint(1, 3)
                chosen_domains = random.sample(
                    mibig_domain_list, min(n_domains, len(mibig_domain_list))
                )
                prot_pos = 0
                for domain in chosen_domains:
                    dom_len = random.randint(20, 80)
                    pd = ProteinDomain(
                        protein=None,
                        domain=domain,
                        start_position=prot_pos,
                        end_position=prot_pos + dom_len,
                        score=round(random.uniform(10.0, 300.0), 1),
                    )
                    mibig_pds_pending.append((pd, mibig_protein_idx))
                    prot_pos += dom_len + random.randint(5, 30)

                mibig_protein_idx += 1

            # Create MibigReference linked to the Bgc
            ref, created = MibigReference.objects.get_or_create(
                accession=f"BGC{i + 1:07d}",
                defaults=dict(
                    compound_name=compound,
                    bgc_class=bgc_class,
                    umap_x=ux,
                    umap_y=uy,
                    embedding=emb,
                    bgc=mibig_bgc,
                ),
            )
            if not created and ref.bgc is None:
                ref.bgc = mibig_bgc
                ref.save(update_fields=["bgc"])
            mibig_refs.append(ref)

        # Bulk create MIBiG proteins, CDS, and protein domains
        Protein.objects.bulk_create(mibig_proteins)
        mibig_cds_to_create = []
        for cds, pidx in mibig_cds_pending:
            cds.protein = mibig_proteins[pidx]
            mibig_cds_to_create.append(cds)
        Cds.objects.bulk_create(mibig_cds_to_create)

        mibig_pds_to_create = []
        for pd, pidx in mibig_pds_pending:
            pd.protein = mibig_proteins[pidx]
            mibig_pds_to_create.append(pd)
        ProteinDomain.objects.bulk_create(mibig_pds_to_create)

        self.stdout.write(
            f"  {len(mibig_refs)} MIBiG references with full BGC records "
            f"({len(mibig_proteins)} proteins, {len(mibig_cds_to_create)} CDS)."
        )

        # 3. Create assemblies with taxonomy
        self.stdout.write("Creating assemblies...")
        assemblies = []
        for i in range(n_assemblies):
            tax = random.choice(_TAXONOMY_POOL)
            is_ts = random.random() < 0.12
            assembly, _ = Assembly.objects.get_or_create(
                accession=f"DISC_ERZ{i:07d}",
                defaults=dict(
                    taxonomy_kingdom=tax[0],
                    taxonomy_phylum=tax[1],
                    taxonomy_class=tax[2],
                    taxonomy_order=tax[3],
                    taxonomy_family=tax[4],
                    taxonomy_genus=tax[5],
                    taxonomy_species=tax[6],
                    organism_name=f"{tax[6]} strain {chr(65 + i % 26)}{i}",
                    is_type_strain=is_ts,
                    type_strain_catalog_url=(
                        f"https://www.dsmz.de/collection/catalogue/details/culture/DSM-{random.randint(1000, 99999)}"
                        if is_ts
                        else None
                    ),
                    genome_size_mb=round(random.uniform(2.5, 12.0), 2),
                    genome_quality=round(random.betavariate(8, 2), 3),
                    isolation_source=random.choice(_ISOLATION_SOURCES),
                ),
            )
            assemblies.append(assembly)

        # 3b. Create biomes and assign to assemblies
        self.stdout.write("Creating biomes...")
        biome_objs = []
        for lineage in _BIOME_LINEAGES:
            biome, _ = Biome.objects.get_or_create(lineage=lineage)
            biome_objs.append(biome)
        for assembly in assemblies:
            if not assembly.biome_id:
                assembly.biome = random.choice(biome_objs)
                assembly.save(update_fields=["biome"])
        self.stdout.write(f"  {len(biome_objs)} biomes assigned.")

        # 4. Create contigs and BGCs for each assembly
        self.stdout.write("Creating contigs and BGCs...")
        all_bgcs = []
        assembly_bgc_map = {}  # assembly_id -> list of bgcs

        for assembly in assemblies:
            n_contigs = random.randint(1, 3)
            assembly_bgcs = []

            for ci in range(n_contigs):
                contig_len = random.randint(50_000, 500_000)
                seq = "ACGT" * (contig_len // 4)  # placeholder sequence
                contig, _ = Contig.objects.get_or_create(
                    sequence_sha256=f"disc_{assembly.id}_{ci}_sha256",
                    defaults=dict(
                        assembly=assembly,
                        mgyc=f"DISC_MGYC{assembly.id:06d}{ci:03d}",
                        accession=f"disc_contig_{assembly.id}_{ci}",
                        name=f"contig_{assembly.id}_{ci}",
                        length=contig_len,
                        sequence=seq,
                    ),
                )

                n_bgcs = random.randint(2, 8)
                pos = random.randint(100, 5000)
                for bi in range(n_bgcs):
                    bgc_size = random.randint(5_000, 80_000)
                    bgc_class_name = random.choice(_BGC_L1_CLASSES)
                    ux, uy = _clustered_umap(bgc_class_name)

                    bgc = Bgc.objects.create(
                        contig=contig,
                        identifier=f"disc_bgc_{assembly.id}_{ci}_{bi}",
                        start_position=pos,
                        end_position=pos + bgc_size,
                        is_partial=random.random() < 0.2,
                        embedding=np.random.randn(1152).astype(np.float32).tolist(),
                        metadata={
                            "umap_x_coord": ux,
                            "umap_y_coord": uy,
                            "detectors": ["antiSMASH"],
                        },
                    )
                    # Assign BGC class
                    BgcBgcClass.objects.get_or_create(
                        bgc=bgc,
                        bgc_class=bgc_class_objs[bgc_class_name],
                    )
                    bgc._class_name = bgc_class_name
                    assembly_bgcs.append(bgc)
                    all_bgcs.append(bgc)
                    pos += bgc_size + random.randint(1000, 10000)

            assembly_bgc_map[assembly.id] = assembly_bgcs

        self.stdout.write(f"  {len(all_bgcs)} BGCs across {n_assemblies} assemblies.")

        # 4b. Create domain architecture data
        self.stdout.write("Creating domain architecture (CDS, Proteins, Domains)...")
        gene_caller, _ = GeneCaller.objects.get_or_create(
            name="Prodigal", defaults={"tool": "Prodigal", "version": "2.6.3"}
        )

        domain_objs = {}
        for acc, name, ref_db in _PFAM_DOMAIN_POOL:
            obj, _ = Domain.objects.get_or_create(
                acc=acc,
                defaults={
                    "name": name,
                    "ref_db": ref_db,
                    "description": f"{name} domain",
                },
            )
            domain_objs[acc] = obj
        domain_list = list(domain_objs.values())

        all_proteins = []
        all_cds_pending = []       # (Cds instance, protein_index)
        all_pds_pending = []       # (ProteinDomain instance, protein_index)
        protein_idx = 0

        for bgc in all_bgcs:
            bgc_length = bgc.end_position - bgc.start_position
            n_cds = random.randint(2, min(6, max(2, bgc_length // 1000)))
            slot_size = bgc_length // n_cds

            for ci in range(n_cds):
                slot_start = bgc.start_position + ci * slot_size
                gene_len = min(random.randint(300, 900), slot_size - 50)
                gene_len = max(gene_len, 150)
                margin = max(11, slot_size - gene_len - 10)
                cds_start = slot_start + random.randint(10, margin)
                cds_end = min(cds_start + gene_len, bgc.end_position)
                cds_start = max(cds_start, bgc.start_position)

                aa_seq = _random_aa(gene_len // 3)
                seq_hash = _sha256(f"{aa_seq}_{protein_idx}")

                protein = Protein(
                    sequence=aa_seq,
                    sequence_sha256=seq_hash,
                    mgyp=f"DISC_MGYP{protein_idx:012d}",
                )
                all_proteins.append(protein)

                cds = Cds(
                    protein=None,  # set after bulk_create
                    contig=bgc.contig,
                    gene_caller=gene_caller,
                    start_position=cds_start,
                    end_position=cds_end,
                    strand=random.choice([1, -1]),
                    protein_identifier=f"DISC_MGYP{protein_idx:012d}",
                    pipeline_version="1.0",
                )
                all_cds_pending.append((cds, protein_idx))

                # 1-3 domains per protein
                n_domains = random.randint(1, 3)
                chosen_domains = random.sample(
                    domain_list, min(n_domains, len(domain_list))
                )
                prot_pos = 0
                for domain in chosen_domains:
                    dom_len = random.randint(20, 80)
                    pd = ProteinDomain(
                        protein=None,  # set after bulk_create
                        domain=domain,
                        start_position=prot_pos,
                        end_position=prot_pos + dom_len,
                        score=round(random.uniform(10.0, 300.0), 1),
                    )
                    all_pds_pending.append((pd, protein_idx))
                    prot_pos += dom_len + random.randint(5, 30)

                protein_idx += 1

        # Bulk create proteins (PostgreSQL returns IDs)
        Protein.objects.bulk_create(all_proteins)

        # Set protein FK and bulk create CDS
        cds_to_create = []
        for cds, pidx in all_cds_pending:
            cds.protein = all_proteins[pidx]
            cds_to_create.append(cds)
        Cds.objects.bulk_create(cds_to_create)

        # Set protein FK and bulk create ProteinDomains
        pds_to_create = []
        for pd, pidx in all_pds_pending:
            pd.protein = all_proteins[pidx]
            pds_to_create.append(pd)
        ProteinDomain.objects.bulk_create(pds_to_create)

        self.stdout.write(
            f"  {len(all_proteins)} Proteins, {len(cds_to_create)} CDS, "
            f"{len(pds_to_create)} ProteinDomains, {len(domain_list)} Domains."
        )

        # 5. Create GCFs and assign memberships
        self.stdout.write("Creating GCFs...")
        n_gcfs = max(5, len(all_bgcs) // 15)
        gcf_list = []
        for gi in range(n_gcfs):
            mibig_ref = random.choice(mibig_refs) if random.random() < 0.3 else None
            gcf = GCF.objects.create(
                family_id=f"GCF_{gi:06d}",
                member_count=0,
                known_chemistry_annotation=(
                    mibig_ref.compound_name if mibig_ref else None
                ),
                mibig_accession=(
                    mibig_ref.accession if mibig_ref else None
                ),
            )
            gcf_list.append(gcf)

        # Assign each BGC to a random GCF
        memberships = []
        for bgc in all_bgcs:
            gcf = random.choice(gcf_list)
            memberships.append(
                GCFMembership(
                    gcf=gcf,
                    bgc=bgc,
                    distance_to_representative=round(random.uniform(0.0, 0.5), 4),
                )
            )
        GCFMembership.objects.bulk_create(memberships)

        # Update member counts and representative BGCs
        for gcf in gcf_list:
            members = gcf.memberships.all()
            gcf.member_count = members.count()
            if gcf.member_count > 0:
                gcf.representative_bgc = members.order_by("distance_to_representative").first().bgc
            gcf.save()

        self.stdout.write(f"  {n_gcfs} GCFs created.")

        # 6. Create NaturalProducts
        self.stdout.write("Creating NaturalProducts...")
        nps = []
        n_nps = min(100, len(all_bgcs) // 3)
        sampled_bgcs = random.sample(all_bgcs, min(n_nps, len(all_bgcs)))
        for bgc in sampled_bgcs:
            l1 = random.choice(list(_NP_CLASSES.keys()))
            l2 = random.choice(list(_NP_CLASSES[l1].keys()))
            l3 = random.choice(_NP_CLASSES[l1][l2])
            nps.append(
                NaturalProduct(
                    name=f"compound_{bgc.id}",
                    smiles=random.choice(_SMILES_POOL),
                    chemical_class_l1=l1,
                    chemical_class_l2=l2,
                    chemical_class_l3=l3,
                    producing_organism=bgc.contig.assembly.organism_name if bgc.contig and bgc.contig.assembly else None,
                    bgc=bgc,
                )
            )
        NaturalProduct.objects.bulk_create(nps)

        # Generate base64 SVG thumbnails for NaturalProducts
        self.stdout.write("Generating compound structure thumbnails...")
        try:
            import base64
            from mgnify_bgcs.services.compound_search_utils import smiles_to_svg
            for np_obj in nps:
                if np_obj.smiles:
                    svg = smiles_to_svg(np_obj.smiles, size=(64, 64))
                    if svg:
                        np_obj.structure_svg_base64 = base64.b64encode(svg.encode()).decode()
            NaturalProduct.objects.bulk_update(nps, ["structure_svg_base64"])
            self.stdout.write("  Thumbnails generated.")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Thumbnail generation failed: {e}"))

        self.stdout.write(f"  {len(nps)} NaturalProducts created.")

        # 7. Compute BgcScores
        self.stdout.write("Computing BgcScores...")
        bgc_scores = []
        for bgc in all_bgcs:
            class_name = getattr(bgc, "_class_name", "Other")
            l2 = None
            l3 = None
            if class_name in _NP_CLASSES:
                l2 = random.choice(list(_NP_CLASSES[class_name].keys()))
                l3 = random.choice(_NP_CLASSES[class_name][l2])

            novelty = round(random.betavariate(2, 5), 4)
            nearest_dist = round(1.0 - novelty, 4)
            nearest_acc = None
            if nearest_dist < 0.6:
                nearest_acc = random.choice(mibig_refs).accession

            gcf_membership = GCFMembership.objects.filter(bgc=bgc).first()

            bgc_scores.append(
                BgcScore(
                    bgc=bgc,
                    novelty_score=novelty,
                    domain_novelty=round(random.betavariate(2, 6), 4),
                    nearest_mibig_accession=nearest_acc,
                    nearest_mibig_distance=nearest_dist,
                    size_kb=round((bgc.end_position - bgc.start_position) / 1000.0, 2),
                    gcf=gcf_membership.gcf if gcf_membership else None,
                    classification_l1=class_name,
                    classification_l2=l2,
                    classification_l3=l3,
                    is_validated=random.random() < 0.03,
                )
            )
        BgcScore.objects.bulk_create(bgc_scores)

        # 8. Compute GenomeScores
        self.stdout.write("Computing GenomeScores...")
        genome_scores = []
        for assembly in assemblies:
            bgcs = assembly_bgc_map.get(assembly.id, [])
            bgc_count = len(bgcs)

            # Diversity: Shannon entropy over L1 classes
            class_counts = {}
            for bgc in bgcs:
                cn = getattr(bgc, "_class_name", "Other")
                class_counts[cn] = class_counts.get(cn, 0) + 1

            total = sum(class_counts.values()) or 1
            entropy = 0.0
            for count in class_counts.values():
                p = count / total
                if p > 0:
                    entropy -= p * math.log2(p)
            # Normalize: max entropy for 7 classes is log2(7) ≈ 2.807
            diversity = round(entropy / math.log2(7), 4) if entropy > 0 else 0.0

            # Novelty: mean of BGC novelty scores
            bgc_novelties = [
                s.novelty_score
                for s in BgcScore.objects.filter(bgc__in=[b.id for b in bgcs])
            ]
            novelty = round(sum(bgc_novelties) / len(bgc_novelties), 4) if bgc_novelties else 0.0

            # Density
            density = 0.0
            if assembly.genome_size_mb and assembly.genome_size_mb > 0:
                density = round(bgc_count / assembly.genome_size_mb / 5.0, 4)  # normalize ~5 bgc/Mb as 1.0
                density = min(density, 1.0)

            genome_scores.append(
                GenomeScore(
                    assembly=assembly,
                    bgc_count=bgc_count,
                    bgc_diversity_score=diversity,
                    bgc_novelty_score=novelty,
                    bgc_density=density,
                    taxonomic_novelty=round(random.betavariate(2, 4), 4),
                    genome_quality=assembly.genome_quality or round(random.betavariate(8, 2), 4),
                    l1_class_count=len(class_counts),
                )
            )
        GenomeScore.objects.bulk_create(genome_scores)

        self.stdout.write(self.style.SUCCESS(
            f"Done! Seeded {n_assemblies} assemblies, {len(all_bgcs)} BGCs, "
            f"{len(all_proteins)} Proteins, {len(pds_to_create)} ProteinDomains, "
            f"{n_gcfs} GCFs, {len(nps)} NaturalProducts, {len(mibig_refs)} MIBiG refs."
        ))
