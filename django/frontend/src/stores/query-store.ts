import { create } from "zustand";
import type { DomainCondition, QueryResultBgc } from "@/api/types";

interface QueryState {
  domainConditions: DomainCondition[];
  logic: "and" | "or";
  similarBgcSourceId: number | null;
  resultBgcIds: number[];
  resultBgcData: QueryResultBgc[];
  smilesQuery: string;
  similarityThreshold: number;
  domainQueryTriggered: boolean;
  chemicalQueryTriggered: boolean;

  addDomainCondition: (condition: DomainCondition) => void;
  removeDomainCondition: (acc: string) => void;
  toggleDomainRequired: (acc: string) => void;
  setLogic: (logic: "and" | "or") => void;
  setSimilarBgcSourceId: (id: number | null) => void;
  setResultBgcIds: (ids: number[]) => void;
  setResultBgcData: (data: QueryResultBgc[]) => void;
  setSmilesQuery: (v: string) => void;
  setSimilarityThreshold: (v: number) => void;
  setDomainQueryTriggered: (v: boolean) => void;
  setChemicalQueryTriggered: (v: boolean) => void;
  clearQuery: () => void;
}

export const useQueryStore = create<QueryState>((set) => ({
  domainConditions: [],
  logic: "and",
  similarBgcSourceId: null,
  resultBgcIds: [],
  resultBgcData: [],
  smilesQuery: "",
  similarityThreshold: 0.5,
  domainQueryTriggered: false,
  chemicalQueryTriggered: false,

  addDomainCondition: (condition) =>
    set((s) => {
      if (s.domainConditions.some((d) => d.acc === condition.acc)) return s;
      return { domainConditions: [...s.domainConditions, condition] };
    }),
  removeDomainCondition: (acc) =>
    set((s) => ({
      domainConditions: s.domainConditions.filter((d) => d.acc !== acc),
    })),
  toggleDomainRequired: (acc) =>
    set((s) => ({
      domainConditions: s.domainConditions.map((d) =>
        d.acc === acc ? { ...d, required: !d.required } : d
      ),
    })),
  setLogic: (logic) => set({ logic }),
  setSimilarBgcSourceId: (id) => set({ similarBgcSourceId: id }),
  setResultBgcIds: (ids) => set({ resultBgcIds: ids }),
  setResultBgcData: (data) => set({ resultBgcData: data }),
  setSmilesQuery: (v) => set({ smilesQuery: v }),
  setSimilarityThreshold: (v) => set({ similarityThreshold: v }),
  setDomainQueryTriggered: (v) => set({ domainQueryTriggered: v }),
  setChemicalQueryTriggered: (v) => set({ chemicalQueryTriggered: v }),
  clearQuery: () =>
    set({
      domainConditions: [],
      logic: "and",
      similarBgcSourceId: null,
      resultBgcIds: [],
      resultBgcData: [],
      smilesQuery: "",
      similarityThreshold: 0.5,
      domainQueryTriggered: false,
      chemicalQueryTriggered: false,
    }),
}));
