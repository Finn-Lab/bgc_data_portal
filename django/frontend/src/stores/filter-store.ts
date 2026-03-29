import { create } from "zustand";

interface FilterState {
  typeStrainOnly: boolean;
  taxonomyKingdom: string;
  taxonomyPhylum: string;
  taxonomyClass: string;
  taxonomyOrder: string;
  taxonomyFamily: string;
  taxonomyGenus: string;
  bgcClass: string;
  npClassL1: string[];
  npClassL2: string[];
  npClassL3: string[];
  search: string;
  biomeLineage: string;
  bgcAccession: string;
  assemblyAccession: string;

  setTypeStrainOnly: (v: boolean) => void;
  setTaxonomy: (rank: string, value: string) => void;
  setBgcClass: (v: string) => void;
  setNpClass: (level: "l1" | "l2" | "l3", values: string[]) => void;
  setSearch: (v: string) => void;
  setBiomeLineage: (v: string) => void;
  setBgcAccession: (v: string) => void;
  setAssemblyAccession: (v: string) => void;
  clearFilters: () => void;
}

const initialState = {
  typeStrainOnly: false,
  taxonomyKingdom: "",
  taxonomyPhylum: "",
  taxonomyClass: "",
  taxonomyOrder: "",
  taxonomyFamily: "",
  taxonomyGenus: "",
  bgcClass: "",
  npClassL1: [] as string[],
  npClassL2: [] as string[],
  npClassL3: [] as string[],
  search: "",
  biomeLineage: "",
  bgcAccession: "",
  assemblyAccession: "",
};

const TAXONOMY_RANKS = [
  "taxonomyKingdom",
  "taxonomyPhylum",
  "taxonomyClass",
  "taxonomyOrder",
  "taxonomyFamily",
  "taxonomyGenus",
] as const;

export const useFilterStore = create<FilterState>((set) => ({
  ...initialState,

  setTypeStrainOnly: (v) => set({ typeStrainOnly: v }),

  setTaxonomy: (rank, value) =>
    set((state) => {
      const key = `taxonomy${rank.charAt(0).toUpperCase()}${rank.slice(1)}` as keyof typeof state;
      const rankIndex = TAXONOMY_RANKS.indexOf(key as (typeof TAXONOMY_RANKS)[number]);
      // Clear lower ranks when a higher rank changes
      const cleared: Record<string, string> = {};
      for (let i = rankIndex + 1; i < TAXONOMY_RANKS.length; i++) {
        cleared[TAXONOMY_RANKS[i]!] = "";
      }
      return { ...cleared, [key]: value };
    }),

  setBgcClass: (v) => set({ bgcClass: v }),
  setNpClass: (level, values) =>
    set(
      level === "l1"
        ? { npClassL1: values }
        : level === "l2"
          ? { npClassL2: values }
          : { npClassL3: values }
    ),
  setSearch: (v) => set({ search: v }),
  setBiomeLineage: (v) => set({ biomeLineage: v }),
  setBgcAccession: (v) => set({ bgcAccession: v }),
  setAssemblyAccession: (v) => set({ assemblyAccession: v }),
  clearFilters: () => set(initialState),
}));
