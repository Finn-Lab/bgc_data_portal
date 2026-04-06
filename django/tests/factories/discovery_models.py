"""
factory_boy DjangoModelFactory definitions for discovery app models.

All factories create discovery models directly — no mgnify_bgcs dependencies.

Usage:
    from tests.factories.discovery_models import DashboardAssemblyFactory
    assembly = DashboardAssemblyFactory()
"""

import random

import factory
import numpy as np
from factory.django import DjangoModelFactory

from discovery.models import (
    BgcEmbedding,
    DashboardAssembly,
    DashboardBgc,
    DashboardBgcClass,
    DashboardContig,
    DashboardDomain,
    DashboardGCF,
    DashboardMibigReference,
    DashboardNaturalProduct,
)


def _embedding() -> list:
    return np.random.randn(1152).astype(np.float32).tolist()


# Curated pools for realistic data generation

_MIBIG_COMPOUNDS = [
    ("erythromycin", "Polyketide"),
    ("vancomycin", "NRP"),
    ("rifamycin", "Polyketide"),
    ("tetracycline", "Polyketide"),
    ("daptomycin", "NRP"),
    ("rapamycin", "Polyketide"),
    ("bleomycin", "NRP"),
    ("avermectin", "Polyketide"),
    ("streptomycin", "Saccharide"),
    ("epothilone", "Polyketide"),
    ("lanthipeptide A", "RiPP"),
    ("nisin", "RiPP"),
    ("geosmin", "Terpene"),
    ("albaflavenone", "Terpene"),
    ("staurosporine", "Alkaloid"),
    ("rebeccamycin", "Alkaloid"),
    ("enterobactin", "NRP"),
    ("bacillibactin", "NRP"),
    ("prodiginine", "Alkaloid"),
    ("desferrioxamine", "NRP"),
    ("salinosporamide", "Polyketide"),
    ("thiostrepton", "RiPP"),
    ("calicheamicin", "Polyketide"),
    ("actinomycin", "NRP"),
    ("chloramphenicol", "Other"),
    ("novobiocin", "Other"),
    ("clavulanic acid", "Other"),
    ("melanin", "Other"),
    ("ectoine", "Other"),
    ("hopanoid", "Terpene"),
]

_NP_CLASSES = {
    "Polyketide": {
        "Macrolide": ["14-membered macrolide", "16-membered macrolide", "Ansamycin"],
        "Aromatic polyketide": ["Tetracycline", "Anthracycline", "Angucycline"],
        "Linear polyketide": ["Polyene", "Polyether", None],
    },
    "NRP": {
        "Cyclic peptide": ["Lipopeptide", "Glycopeptide", "Depsipeptide"],
        "Linear peptide": ["Siderophore", None, None],
    },
    "Alkaloid": {
        "Indole alkaloid": ["Bisindole", "Carbazole", None],
        "Pyrrolidine": [None, None, None],
    },
    "RiPP": {
        "Lanthipeptide": ["Class I", "Class II", None],
        "Thiopeptide": [None, None, None],
        "Sactipeptide": [None, None, None],
    },
    "Terpene": {
        "Sesquiterpene": [None, None, None],
        "Diterpene": [None, None, None],
    },
    "Saccharide": {
        "Aminoglycoside": ["4,6-disubstituted", None, None],
        "Oligosaccharide": [None, None, None],
    },
    "Other": {
        "Phosphonate": [None, None, None],
        "Aminocoumarin": [None, None, None],
    },
}

_SMILES_POOL = [
    "CC1OC(=O)C(C)C(OC2CC(C)(OC)C(O)C(C)O2)C(C)C(OC2OC(C)CC(N(C)C)C2O)C(C)(O)CC(C)C(=O)C(C)C(O)C1(C)O",
    "CC(=O)NC1C(O)C(O)C(CO)OC1OC1C(O)C(OC2OC(CO)C(O)C(N)C2O)C(O)C(CO)O1",
    "CC1=CC(O)=C2C(=O)C3=C(O)C(N(C)C)=CC(O)=C3CC2=C1",
    "O=C(O)C1=CC=C(N)C=C1",
    "CC(O)CC(=O)OC1CC(O)C(C)C(OC2CC(C)C(O)C(C)O2)C(C)C(=O)CC(O)C(C)C(=O)C(C)C1OC1CC(N(C)C)C(O)C(C)O1",
    "CC1OC(OC2C(O)C(O)CC(O2)C2=CC3=CC(=CC(O)=C3C(=O)C2)OC)CC(N)C1O",
    "CCC(C)C(NC(=O)C(CC(C)C)NC(=O)C(CCC(=O)O)NC(=O)C(CC(=O)O)NC(=O)C(NC=O)CCCN)C(=O)O",
    "OC1=CC=C(C=C1)C(=O)O",
    "CC1=C(C=CC=C1O)O",
    "CC1OC(O)CC1=O",
    "CC(CC1=CNC2=CC=CC=C12)NC",
    "OC(=O)CCCCC1SCC2NC(=O)NC12",
    "CC(C)CC1NC(=O)C(CC(=O)O)NC(=O)C(CC2=CC=CC=C2)NC(=O)C(CO)NC1=O",
    "OC(=O)C1CCCN1",
    "CC1=CC=CC=C1NC(=O)C1=CC=CC(O)=C1O",
    "OC1C(O)C(OC1CO)N1C=NC2=C1N=CN=C2N",
    "CC(=O)OC1CC2CCC3C(CCC4(C)C3CC=C3CC(O)CCC34C)C2(C)CC1OC(=O)C",
    "CC1(C)CCC2(CCC3(C)C(=CCC4C5(C)CCC(O)C(C)(C)C5CCC43C)C2C1)C(=O)O",
    "O=C1C=CC(=O)C2=C1C=CC=C2",
    "CC1OC(=O)CC(O)C1O",
]


# ── Core model factories ─────────────────────────────────────────────────────


class DashboardAssemblyFactory(DjangoModelFactory):
    class Meta:
        model = DashboardAssembly
        django_get_or_create = ("assembly_accession",)

    assembly_accession = factory.Sequence(lambda n: f"GCA_TEST_{n:06d}")
    organism_name = factory.LazyFunction(
        lambda: random.choice([
            "Streptomyces coelicolor",
            "Streptomyces griseus",
            "Amycolatopsis mediterranei",
            "Bacillus subtilis",
            "Pseudomonas fluorescens",
        ])
    )
    source_assembly_id = factory.Sequence(lambda n: n + 1)
    assembly_type = 2  # genome
    dominant_taxonomy_path = "Bacteria.Actinomycetota.Actinomycetia.Streptomycetales.Streptomycetaceae.Streptomyces"
    dominant_taxonomy_label = factory.LazyAttribute(lambda o: o.organism_name)
    biome_path = "root.Environmental.Terrestrial.Soil"
    is_type_strain = False
    assembly_size_mb = factory.LazyFunction(lambda: round(random.uniform(4.0, 12.0), 2))
    assembly_quality = factory.LazyFunction(lambda: round(random.betavariate(8, 2), 4))

    # Denormalized scores
    bgc_count = factory.LazyFunction(lambda: random.randint(1, 30))
    l1_class_count = factory.LazyFunction(lambda: random.randint(1, 7))
    bgc_diversity_score = factory.LazyFunction(lambda: round(random.betavariate(3, 2), 4))
    bgc_novelty_score = factory.LazyFunction(lambda: round(random.betavariate(2, 5), 4))
    bgc_density = factory.LazyFunction(lambda: round(random.betavariate(2, 3), 4))
    taxonomic_novelty = factory.LazyFunction(lambda: round(random.betavariate(2, 4), 4))
    pctl_diversity = factory.LazyFunction(lambda: round(random.uniform(0, 100), 1))
    pctl_novelty = factory.LazyFunction(lambda: round(random.uniform(0, 100), 1))
    pctl_density = factory.LazyFunction(lambda: round(random.uniform(0, 100), 1))


class DashboardContigFactory(DjangoModelFactory):
    class Meta:
        model = DashboardContig

    assembly = factory.SubFactory(DashboardAssemblyFactory)
    accession = factory.Sequence(lambda n: f"MGYC_TEST_{n:08d}")
    length = factory.LazyFunction(lambda: random.randint(50_000, 1_000_000))
    taxonomy_path = "Bacteria.Actinomycetota.Actinomycetia.Streptomycetales.Streptomycetaceae.Streptomyces"
    source_contig_id = factory.Sequence(lambda n: n + 1)


class DashboardBgcFactory(DjangoModelFactory):
    class Meta:
        model = DashboardBgc
        exclude = ("_classification",)

    assembly = factory.SubFactory(DashboardAssemblyFactory)
    contig = factory.SubFactory(DashboardContigFactory, assembly=factory.SelfAttribute("..assembly"))
    bgc_accession = factory.Sequence(lambda n: f"MGYB{n:08d}.ANT.1.01")
    contig_accession = factory.LazyAttribute(lambda o: o.contig.accession)
    start_position = factory.LazyFunction(lambda: random.randint(1000, 50_000))
    end_position = factory.LazyAttribute(lambda o: o.start_position + random.randint(5000, 80_000))
    source_bgc_id = factory.Sequence(lambda n: n + 1)

    # Classification
    @factory.lazy_attribute
    def _classification(self):
        l1 = random.choice(list(_NP_CLASSES.keys()))
        l2 = random.choice(list(_NP_CLASSES[l1].keys()))
        l3 = random.choice(_NP_CLASSES[l1][l2])
        return l1, l2, l3

    @factory.lazy_attribute
    def classification_l1(self):
        return self._classification[0]

    @factory.lazy_attribute
    def classification_l2(self):
        return self._classification[1]

    @factory.lazy_attribute
    def classification_l3(self):
        return self._classification[2] or ""

    @factory.lazy_attribute
    def classification_path(self):
        parts = [self.classification_l1, self.classification_l2]
        if self.classification_l3:
            parts.append(self.classification_l3)
        return ".".join(parts)

    # Scores
    novelty_score = factory.LazyFunction(lambda: round(random.betavariate(2, 5), 4))
    domain_novelty = factory.LazyFunction(lambda: round(random.betavariate(2, 6), 4))
    size_kb = factory.LazyFunction(lambda: round(random.uniform(5.0, 120.0), 2))
    nearest_mibig_distance = factory.LazyFunction(lambda: round(random.uniform(0.0, 1.0), 4))

    @factory.lazy_attribute
    def nearest_mibig_accession(self):
        return f"BGC{random.randint(1, 2500):07d}" if self.nearest_mibig_distance < 0.5 else ""

    # Flags
    is_partial = False
    is_validated = factory.LazyFunction(lambda: random.random() < 0.05)
    is_mibig = False

    # UMAP
    umap_x = factory.LazyFunction(lambda: round(random.uniform(-10, 10), 4))
    umap_y = factory.LazyFunction(lambda: round(random.uniform(-10, 10), 4))


# ── Related model factories ──────────────────────────────────────────────────


class DashboardGCFFactory(DjangoModelFactory):
    class Meta:
        model = DashboardGCF
        django_get_or_create = ("family_id",)

    family_id = factory.Sequence(lambda n: f"GCF_{n:06d}")
    representative_bgc = factory.SubFactory(DashboardBgcFactory)
    member_count = factory.LazyFunction(lambda: random.randint(3, 50))
    known_chemistry_annotation = factory.LazyFunction(
        lambda: random.choice(["", "", "polyketide synthase", "NRPS", "lanthipeptide", "siderophore"])
    )
    mibig_accession = factory.LazyFunction(
        lambda: f"BGC{random.randint(1, 2500):07d}" if random.random() < 0.3 else ""
    )
    mean_novelty = factory.LazyFunction(lambda: round(random.betavariate(2, 5), 4))
    mibig_count = factory.LazyFunction(lambda: random.randint(0, 5))


class DashboardNaturalProductFactory(DjangoModelFactory):
    class Meta:
        model = DashboardNaturalProduct
        exclude = ("_np_class",)

    name = factory.Faker("word")
    smiles = factory.LazyFunction(lambda: random.choice(_SMILES_POOL))
    bgc = factory.SubFactory(DashboardBgcFactory)

    @factory.lazy_attribute
    def _np_class(self):
        l1 = random.choice(list(_NP_CLASSES.keys()))
        l2 = random.choice(list(_NP_CLASSES[l1].keys()))
        l3 = random.choice(_NP_CLASSES[l1][l2])
        return l1, l2, l3

    @factory.lazy_attribute
    def chemical_class_l1(self):
        return self._np_class[0]

    @factory.lazy_attribute
    def chemical_class_l2(self):
        return self._np_class[1]

    @factory.lazy_attribute
    def chemical_class_l3(self):
        return self._np_class[2] or ""

    @factory.lazy_attribute
    def producing_organism(self):
        return random.choice([
            "Streptomyces coelicolor", "Streptomyces griseus",
            "Amycolatopsis mediterranei", "Bacillus subtilis",
            "Pseudomonas fluorescens", "Myxococcus xanthus",
            "",
        ])


class DashboardMibigReferenceFactory(DjangoModelFactory):
    class Meta:
        model = DashboardMibigReference
        django_get_or_create = ("accession",)
        exclude = ("_compound_info",)

    accession = factory.Sequence(lambda n: f"BGC{n:07d}")
    embedding = factory.LazyFunction(_embedding)

    @factory.lazy_attribute
    def _compound_info(self):
        return random.choice(_MIBIG_COMPOUNDS)

    @factory.lazy_attribute
    def compound_name(self):
        return self._compound_info[0]

    @factory.lazy_attribute
    def bgc_class(self):
        return self._compound_info[1]

    @factory.lazy_attribute
    def umap_x(self):
        return round(random.uniform(-10, 10), 4)

    @factory.lazy_attribute
    def umap_y(self):
        return round(random.uniform(-10, 10), 4)


class BgcEmbeddingFactory(DjangoModelFactory):
    class Meta:
        model = BgcEmbedding

    bgc = factory.SubFactory(DashboardBgcFactory)
    vector = factory.LazyFunction(_embedding)


class DashboardBgcClassFactory(DjangoModelFactory):
    class Meta:
        model = DashboardBgcClass
        django_get_or_create = ("name",)

    name = factory.LazyFunction(
        lambda: random.choice(["Polyketide", "NRP", "Alkaloid", "RiPP", "Terpene", "Saccharide", "Other"])
    )
    bgc_count = factory.LazyFunction(lambda: random.randint(1, 500))


class DashboardDomainFactory(DjangoModelFactory):
    class Meta:
        model = DashboardDomain
        django_get_or_create = ("acc",)

    acc = factory.Sequence(lambda n: f"PF{n:05d}")
    name = factory.Faker("word")
    ref_db = "Pfam"
    bgc_count = factory.LazyFunction(lambda: random.randint(1, 200))
