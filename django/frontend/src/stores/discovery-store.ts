import { create } from "zustand";
import type { NrbScatterAxis, RegionCds } from "@/api/types";

/**
 * Session state for the v2 Discovery dashboard.
 *
 * Persistence is intentionally OFF (per design decision): the reference NRB
 * + compare slot reset on reload. URL state lives in route params, not here.
 */

export type ResultsTab = "roster" | "variables" | "umap";

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
  setQueryResult: (
    ids: number[] | null,
    similarity?: Record<number, number> | null,
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
  taxonomyPath: string;
  bgcClass: string;
  biomeLineage: string;
  assemblyAccession: string;
  organism: string;
}

export const EMPTY_APPLIED_FILTERS: AppliedNrbFilters = {
  sourceNames: [],
  taxonomyPath: "",
  bgcClass: "",
  biomeLineage: "",
  assemblyAccession: "",
  organism: "",
};

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
  setQueryResult: (ids, similarity = null) =>
    set({
      resultNrbIds: ids,
      resultSimilarityById: similarity,
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
      appliedFilters: EMPTY_APPLIED_FILTERS,
    }),
}));
