export interface TooltipEntry {
  /** Short explanation (1-2 sentences, plain text) */
  text: string;
  /** Optional absolute URL to the relevant Quarto docs page */
  docsUrl?: string;
}

export const TOOLTIP_REGISTRY: Record<string, TooltipEntry> = {
  // ── Assembly-level scores ──────────────────────────────────────────
  novelty_score_assembly: {
    text: "Average novelty across all BGCs in this assembly. Higher values (closer to 1) indicate BGC repertoires collectively dissimilar from all characterised chemistry in MIBiG.",
    docsUrl: "/docs/scores-metrics.html#assembly-level-scores",
  },
  diversity_score: {
    text: "Normalised richness of BGC broad-class types present (0\u20131). An assembly spanning Polyketide + RiPP + Terpene + NRP scores higher than one with only Polyketides.",
    docsUrl: "/docs/scores-metrics.html#assembly-level-scores",
  },
  density: {
    text: "BGC count per megabase of assembled sequence. A high-density organism is a prolific natural product producer relative to its genome size.",
    docsUrl: "/docs/scores-metrics.html#assembly-level-scores",
  },
  taxonomic_novelty: {
    text: "Measures how taxonomically distant this organism is from well-characterised BGC producers. High values indicate an underexplored lineage.",
    docsUrl: "/docs/scores-metrics.html#assembly-level-scores",
  },

  // ── BGC-level scores ───────────────────────────────────────────────
  novelty_score_bgc: {
    text: "Cosine distance (0\u20131) to the nearest validated (MIBiG) BGC in embedding space. 0 = identical to a known cluster; 1 = maximally distant from all known chemistry.",
    docsUrl: "/docs/scores-metrics.html#bgc-level-scores",
  },
  domain_novelty: {
    text: "Fraction (0\u20131) of protein domains in this BGC that are unique \u2014 not shared with other BGCs in the database. High values indicate an unusual enzymatic architecture.",
    docsUrl: "/docs/scores-metrics.html#bgc-level-scores",
  },
  nearest_validated_distance: {
    text: "Raw cosine distance to the closest validated (MIBiG) BGC. Lower values mean this cluster closely resembles a known characterised compound.",
    docsUrl: "/docs/scores-metrics.html#bgc-level-scores",
  },

  // ── Concepts ───────────────────────────────────────────────────────
  gcf_definition: {
    text: "Gene Cluster Family \u2014 a group of BGCs from different assemblies that share high sequence-embedding similarity. A large GCF with zero validated members is an uncharacterised but widespread biosynthetic strategy.",
    docsUrl: "/docs/gcf-explained.html",
  },
  mibig_validated: {
    text: "This BGC has a verified match in MIBiG, the repository of experimentally characterised biosynthetic gene clusters linked to known compounds.",
    docsUrl: "/docs/mibig-validated.html",
  },
  novel_singleton: {
    text: "This BGC does not cluster with any other BGC in the database into a GCF. It forms a family of one \u2014 the strongest possible novelty signal.",
    docsUrl: "/docs/gcf-explained.html#novel-singletons",
  },
  type_strain: {
    text: "A designated reference strain for its species, typically available for purchase from a culture collection (e.g. DSMZ, ATCC). Enable the Type Strain filter to restrict to purchasable organisms.",
    docsUrl: "/docs/glossary.html#type-strain",
  },
  chemont_class: {
    text: "Chemical Ontology (ChemOnt) classification \u2014 a hierarchical taxonomy of ~4,825 chemical classes describing the predicted product chemistry. Independent of BGC class, which describes the enzymatic machinery.",
    docsUrl: "/docs/chemont.html",
  },
  bgc_class_toggle: {
    text: "Filter by biosynthetic machinery type (Polyketide, NRP, RiPP, Terpene, Saccharide, Alkaloid, Other). These reflect the enzymatic strategy, not the product\u2019s chemical structure.",
    docsUrl: "/docs/bgc-classes.html",
  },

  // ── Similarity methods ─────────────────────────────────────────────
  sorensen_dice: {
    text: "S\u00F8rensen-Dice coefficient: fraction of query domains matched vs. total domains in the union (0\u20131). Used for domain query similarity scoring.",
    docsUrl: "/docs/similarity-scores.html#sorensen-dice",
  },
  tanimoto: {
    text: "Tanimoto coefficient comparing Morgan fingerprints of predicted natural products (0\u20131). Used in chemical structure (SMILES) search.",
    docsUrl: "/docs/similarity-scores.html#tanimoto",
  },
  phmmer_bitscore: {
    text: "HMMER bit score for the full target sequence. Higher = more significant. 30 is HMMER's conventional weak-significance cut; \u2265200 indicates a very strong homolog.",
    docsUrl: "/docs/similarity-scores.html#phmmer",
  },
  phmmer_pident: {
    text: "Aggregate percent identity across all aligned domains of the best phmmer hit (identical residues / aligned columns). 70% is a stringent default; lower for distant homologs.",
    docsUrl: "/docs/similarity-scores.html#phmmer",
  },
  phmmer_qcoverage: {
    text: "Fraction of the query sequence covered by the union of phmmer domain envelopes in the matched protein. Low values mean only part of your query aligned.",
    docsUrl: "/docs/similarity-scores.html#phmmer",
  },

  // ── Filters ────────────────────────────────────────────────────────
  biome_lineage: {
    text: "GOLD Ecosystem Classification path for metagenome assemblies, e.g. root:Environmental:Terrestrial:Soil. Filter by typing a path substring.",
    docsUrl: "/docs/biome-ontology.html",
  },
};
