from django.db import models
from pgvector.django import VectorField, HnswIndex


class GCF(models.Model):
    """Gene Cluster Family — a group of BGCs with similar protein-level architecture."""

    id = models.AutoField(primary_key=True)
    family_id = models.CharField(max_length=255, unique=True, db_index=True)
    representative_bgc = models.ForeignKey(
        "mgnify_bgcs.Bgc",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="represented_gcf",
    )
    member_count = models.IntegerField(default=0)
    known_chemistry_annotation = models.CharField(max_length=255, blank=True, null=True)
    mibig_accession = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "GCF"
        verbose_name_plural = "GCFs"

    def __str__(self):
        return self.family_id


class GCFMembership(models.Model):
    """Associates a BGC with exactly one GCF."""

    id = models.AutoField(primary_key=True)
    gcf = models.ForeignKey(GCF, on_delete=models.CASCADE, related_name="memberships")
    bgc = models.OneToOneField(
        "mgnify_bgcs.Bgc",
        on_delete=models.CASCADE,
        related_name="gcf_membership",
    )
    distance_to_representative = models.FloatField(default=0.0)

    class Meta:
        verbose_name = "GCF membership"
        verbose_name_plural = "GCF memberships"

    def __str__(self):
        return f"{self.bgc_id} → {self.gcf.family_id}"


class NaturalProduct(models.Model):
    """A characterized natural product linked to its producing BGC."""

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    smiles = models.TextField()
    chemical_class_l1 = models.CharField(max_length=100)
    chemical_class_l2 = models.CharField(max_length=100, blank=True, null=True)
    chemical_class_l3 = models.CharField(max_length=100, blank=True, null=True)
    structure_svg_base64 = models.TextField(blank=True, default="")
    producing_organism = models.CharField(max_length=255, blank=True, null=True)
    bgc = models.ForeignKey(
        "mgnify_bgcs.Bgc",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="natural_products",
    )

    class Meta:
        indexes = [
            models.Index(fields=["chemical_class_l1"], name="idx_np_class_l1"),
            models.Index(
                fields=["chemical_class_l1", "chemical_class_l2"],
                name="idx_np_class_l1_l2",
            ),
        ]

    def __str__(self):
        return self.name


class MibigReference(models.Model):
    """A MIBiG reference cluster — known chemistry landmark in the UMAP space."""

    id = models.AutoField(primary_key=True)
    accession = models.CharField(max_length=50, unique=True, db_index=True)
    compound_name = models.CharField(max_length=255)
    bgc_class = models.CharField(max_length=100)
    umap_x = models.FloatField()
    umap_y = models.FloatField()
    embedding = VectorField(dimensions=1152, null=True, blank=True)

    class Meta:
        indexes = [
            HnswIndex(
                fields=["embedding"],
                name="mibig_embedding_hnsw",
                opclasses=["vector_cosine_ops"],
                m=16,
                ef_construction=512,
            ),
        ]

    def __str__(self):
        return f"{self.accession} ({self.compound_name})"


class GenomeScore(models.Model):
    """Precomputed genome-level (Assembly) scores for the discovery dashboard."""

    assembly = models.OneToOneField(
        "mgnify_bgcs.Assembly",
        on_delete=models.CASCADE,
        related_name="genome_score",
        primary_key=True,
    )
    bgc_count = models.IntegerField(default=0)
    bgc_diversity_score = models.FloatField(default=0.0)
    bgc_novelty_score = models.FloatField(default=0.0)
    bgc_density = models.FloatField(default=0.0)
    taxonomic_novelty = models.FloatField(default=0.0)
    genome_quality = models.FloatField(default=0.0)
    l1_class_count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Scores for {self.assembly.accession}"


class BgcScore(models.Model):
    """Precomputed BGC-level scores for the discovery dashboard."""

    bgc = models.OneToOneField(
        "mgnify_bgcs.Bgc",
        on_delete=models.CASCADE,
        related_name="bgc_score",
        primary_key=True,
    )
    novelty_score = models.FloatField(default=0.0)
    domain_novelty = models.FloatField(default=0.0)
    nearest_mibig_accession = models.CharField(max_length=50, blank=True, null=True)
    nearest_mibig_distance = models.FloatField(blank=True, null=True)
    size_kb = models.FloatField(default=0.0)
    gcf = models.ForeignKey(
        GCF,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bgc_scores",
    )
    classification_l1 = models.CharField(max_length=100, blank=True, default="")
    classification_l2 = models.CharField(max_length=100, blank=True, null=True)
    classification_l3 = models.CharField(max_length=100, blank=True, null=True)
    is_validated = models.BooleanField(default=False)

    def __str__(self):
        return f"Scores for BGC {self.bgc_id}"
