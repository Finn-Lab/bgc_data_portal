import { create } from "zustand";

interface FilterState {
  sourceNames: string[];
  detectorTools: string[];
  taxonomyPath: string;
  assemblyType: string;
  bgcClass: string;
  npClassL1: string[];
  npClassL2: string[];
  npClassL3: string[];
  chemontIds: string[];
  search: string;
  biomeLineage: string;
  bgcAccession: string;
  assemblyAccession: string;
  assemblyIds: string;
  exploreQueryTriggered: boolean;

  setSourceNames: (v: string[]) => void;
  setDetectorTools: (v: string[]) => void;
  setTaxonomyPath: (value: string) => void;
  setAssemblyType: (v: string) => void;
  setBgcClass: (v: string) => void;
  setNpClass: (level: "l1" | "l2" | "l3", values: string[]) => void;
  setChemontIds: (ids: string[]) => void;
  setSearch: (v: string) => void;
  setBiomeLineage: (v: string) => void;
  setBgcAccession: (v: string) => void;
  setAssemblyAccession: (v: string) => void;
  setAssemblyIds: (v: string) => void;
  runExploreQuery: () => void;
  clearFilters: () => void;
}

const initialState = {
  sourceNames: [] as string[],
  detectorTools: [] as string[],
  taxonomyPath: "",
  assemblyType: "",
  bgcClass: "",
  npClassL1: [] as string[],
  npClassL2: [] as string[],
  npClassL3: [] as string[],
  chemontIds: [] as string[],
  search: "",
  biomeLineage: "",
  bgcAccession: "",
  assemblyAccession: "",
  assemblyIds: "",
  exploreQueryTriggered: false,
};

export const useFilterStore = create<FilterState>((set) => ({
  ...initialState,

  setSourceNames: (v) => set({ sourceNames: v, exploreQueryTriggered: false }),

  setDetectorTools: (v) => set({ detectorTools: v, exploreQueryTriggered: false }),

  setTaxonomyPath: (value) => set({ taxonomyPath: value, exploreQueryTriggered: false }),

  setAssemblyType: (v) => set({ assemblyType: v, exploreQueryTriggered: false }),

  setBgcClass: (v) => set({ bgcClass: v, exploreQueryTriggered: false }),
  setNpClass: (level, values) =>
    set(
      level === "l1"
        ? { npClassL1: values, exploreQueryTriggered: false }
        : level === "l2"
          ? { npClassL2: values, exploreQueryTriggered: false }
          : { npClassL3: values, exploreQueryTriggered: false }
    ),
  setChemontIds: (ids) => set({ chemontIds: ids, exploreQueryTriggered: false }),
  setSearch: (v) => set({ search: v, exploreQueryTriggered: false }),
  setBiomeLineage: (v) => set({ biomeLineage: v, exploreQueryTriggered: false }),
  setBgcAccession: (v) => set({ bgcAccession: v, exploreQueryTriggered: false }),
  setAssemblyAccession: (v) => set({ assemblyAccession: v, exploreQueryTriggered: false }),
  setAssemblyIds: (v) => set({ assemblyIds: v, exploreQueryTriggered: false }),
  runExploreQuery: () => set({ exploreQueryTriggered: true }),
  clearFilters: () => set(initialState),
}));
