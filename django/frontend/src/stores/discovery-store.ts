import { create } from "zustand";
import type { NrbScatterAxis, RegionCds } from "@/api/types";

/**
 * Session state for the v2 Discovery dashboard.
 *
 * Persistence is intentionally OFF (per design decision): the reference NRB
 * + compare slot reset on reload. URL state lives in route params, not here.
 */

export type ResultsTab = "roster" | "variables" | "umap";

/** Which advanced-query path produced the current ``resultNrbIds`` set.
 *  Lets the roster swap the "Sim." column for sequence-search-specific
 *  columns. ``null`` = no advanced query (filter-only run or fresh load). */
export type SearchSource =
  | "sequence"
  | "domain"
  | "domain_architecture"
  | "chemical"
  | "similar_nrb"
  | null;

interface DiscoveryState {
  // Reference NRB (top-right detail card, pinned across left-clicks).
  referenceNrbId: number | null;
  setReferenceNrbId: (id: number | null) => void;

  // Compare slot NRB (bottom-right detail card; updated on left-click).
  compareNrbId: number | null;
  setCompareNrbId: (id: number | null) => void;

  // Selected CDS feeds the Protein Information panel below the detail
  // stack. We carry the full ``RegionCds`` object so the panel can render
  // Pfam annotations + protein sequence without an extra round-trip.
  selectedCds: RegionCds | null;
  setSelectedCds: (cds: RegionCds | null) => void;

  // Results card tab + axis selectors for the Variables Map.
  activeResultsTab: ResultsTab;
  setActiveResultsTab: (tab: ResultsTab) => void;

  variablesAxisX: NrbScatterAxis;
  variablesAxisY: NrbScatterAxis;
  setVariablesAxes: (x: NrbScatterAxis, y: NrbScatterAxis) => void;

  // Run Query result set — NRB id allow-list applied by the roster + maps
  // when populated. Null = no active query, show everything.
  resultNrbIds: number[] | null;
  /** Optional NRB → similarity-score lookup populated by sequence/domain
   *  queries; used to colour scatter points by score. */
  resultSimilarityById: Record<number, number> | null;
  /** Optional NRB → best-hit protein_id lookup populated by sequence
   *  protein search; overlaid onto roster rows since the standard
   *  ``/nrbs/roster/`` endpoint does not carry per-query data. */
  resultBestHitProteinById: Record<number, string> | null;
  /** Percent identity (0–100) of the winning CDS per NRB; feeds the
   *  Variables Map "Identity" axis. */
  resultPidentById: Record<number, number> | null;
  /** Query coverage (0–100) of the winning CDS per NRB; feeds the
   *  Variables Map "Query coverage" axis. */
  resultQcoverageById: Record<number, number> | null;
  /** Which advanced-query path produced ``resultNrbIds``; toggles the
   *  bitscore + best-hit-protein columns in the roster. */
  searchSource: SearchSource;
  setQueryResult: (
    ids: number[] | null,
    similarity?: Record<number, number> | null,
    source?: SearchSource,
    bestHitProtein?: Record<number, string> | null,
    pident?: Record<number, number> | null,
    qcoverage?: Record<number, number> | null,
  ) => void;

  // Snapshot of filter-store values taken when the user last pressed Run
  // Query. The roster/maps key off this — toggling a chip without pressing
  // Run Query does NOT refetch.
  appliedFilters: AppliedNrbFilters;
  setAppliedFilters: (filters: AppliedNrbFilters) => void;

  // Convenience: clear all selections (e.g., on a fresh Run Query).
  clearSelections: () => void;
}

export interface AppliedNrbFilters {
  sourceNames: string[];
  detectorTools: string[];
  assemblyType: string;
  taxonomyPath: string;
  bgcClass: string;
  gcfPath: string;
  chemontIds: string[];
  biomeLineage: string;
  bgcAccession: string;
  assemblyAccession: string;
  assemblyIds: string;
  organism: string;
}

export const EMPTY_APPLIED_FILTERS: AppliedNrbFilters = {
  sourceNames: [],
  detectorTools: [],
  assemblyType: "",
  taxonomyPath: "",
  bgcClass: "",
  gcfPath: "",
  chemontIds: [],
  biomeLineage: "",
  bgcAccession: "",
  assemblyAccession: "",
  assemblyIds: "",
  organism: "",
};

/** True when no filter chip is set in the applied snapshot.
 *  Combined with ``resultNrbIds == null`` it gates the dashboard's
 *  empty-state CTA so we never fire an unbounded fetch on landing. */
export function isAppliedFiltersEmpty(applied: AppliedNrbFilters): boolean {
  return (
    applied.sourceNames.length === 0 &&
    applied.detectorTools.length === 0 &&
    applied.chemontIds.length === 0 &&
    applied.assemblyType === "" &&
    applied.taxonomyPath === "" &&
    applied.bgcClass === "" &&
    applied.gcfPath === "" &&
    applied.biomeLineage === "" &&
    applied.bgcAccession === "" &&
    applied.assemblyAccession === "" &&
    applied.assemblyIds === "" &&
    applied.organism === ""
  );
}

/**
 * Build the NRB API query-string surface from an applied-filter snapshot
 * plus the optional Run Query allow-list. Empty values are dropped so the
 * resulting object only carries active params (cleaner cache keys and URLs).
 *
 * Used by ``NrbRosterTable``, the UMAP hook and the Variables-Map scatter
 * hook so all three stay in lockstep with the same filter contract.
 */
export function appliedFiltersToApiParams(
  applied: AppliedNrbFilters,
  resultNrbIds: number[] | null = null,
): Record<string, string> {
  const params: Record<string, string> = {};
  if (applied.sourceNames.length > 0) {
    params.source_names = applied.sourceNames.join(",");
  }
  if (applied.detectorTools.length > 0) {
    params.detector_tools = applied.detectorTools.join(",");
  }
  if (applied.assemblyType) params.assembly_type = applied.assemblyType;
  if (applied.taxonomyPath) params.taxonomy_path = applied.taxonomyPath;
  if (applied.bgcClass) params.bgc_class = applied.bgcClass;
  if (applied.gcfPath) params.leaf_path_prefix = applied.gcfPath;
  if (applied.chemontIds.length > 0) {
    params.chemont_ids = applied.chemontIds.join(",");
  }
  if (applied.biomeLineage) params.biome_lineage = applied.biomeLineage;
  if (applied.bgcAccession) params.bgc_accession = applied.bgcAccession;
  if (applied.assemblyAccession) {
    params.assembly_accession = applied.assemblyAccession;
  }
  if (applied.assemblyIds) params.assembly_ids = applied.assemblyIds;
  if (applied.organism) params.organism = applied.organism;
  if (resultNrbIds && resultNrbIds.length > 0) {
    params.nrb_ids = resultNrbIds.join(",");
  }
  return params;
}

export const useDiscoveryStore = create<DiscoveryState>((set) => ({
  referenceNrbId: null,
  setReferenceNrbId: (id) => set({ referenceNrbId: id }),

  compareNrbId: null,
  setCompareNrbId: (id) => set({ compareNrbId: id }),

  selectedCds: null,
  setSelectedCds: (cds) => set({ selectedCds: cds }),

  activeResultsTab: "roster",
  setActiveResultsTab: (tab) => set({ activeResultsTab: tab }),

  variablesAxisX: "novelty_score",
  variablesAxisY: "domain_novelty",
  setVariablesAxes: (x, y) => set({ variablesAxisX: x, variablesAxisY: y }),

  resultNrbIds: null,
  resultSimilarityById: null,
  resultBestHitProteinById: null,
  resultPidentById: null,
  resultQcoverageById: null,
  searchSource: null,
  setQueryResult: (
    ids,
    similarity = null,
    source = null,
    bestHitProtein = null,
    pident = null,
    qcoverage = null,
  ) =>
    set({
      resultNrbIds: ids,
      resultSimilarityById: similarity,
      resultBestHitProteinById: bestHitProtein,
      resultPidentById: pident,
      resultQcoverageById: qcoverage,
      searchSource: source,
      // A fresh query resets compare/protein selections.
      compareNrbId: null,
      selectedCds: null,
    }),

  appliedFilters: EMPTY_APPLIED_FILTERS,
  setAppliedFilters: (filters) => set({ appliedFilters: filters }),

  clearSelections: () =>
    set({
      referenceNrbId: null,
      compareNrbId: null,
      selectedCds: null,
      resultNrbIds: null,
      resultSimilarityById: null,
      resultBestHitProteinById: null,
      resultPidentById: null,
      resultQcoverageById: null,
      searchSource: null,
      appliedFilters: EMPTY_APPLIED_FILTERS,
    }),
}));
