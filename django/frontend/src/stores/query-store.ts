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
  sequenceQuery: string;
  sequenceMinBitscore: number;
  sequenceMinPident: number;
  sequenceMinQcov: number;
  sequenceTaskId: string | null;
  domainQueryTriggered: boolean;
  chemicalQueryTriggered: boolean;
  sequenceQueryTriggered: boolean;

  // Per-query result storage for intersection
  domainResultData: QueryResultBgc[];
  chemicalResultData: QueryResultBgc[];
  sequenceResultData: QueryResultBgc[];

  addDomainCondition: (condition: DomainCondition) => void;
  removeDomainCondition: (acc: string) => void;
  toggleDomainRequired: (acc: string) => void;
  setLogic: (logic: "and" | "or") => void;
  setSimilarBgcSourceId: (id: number | null) => void;
  setResultBgcIds: (ids: number[]) => void;
  setResultBgcData: (data: QueryResultBgc[]) => void;
  setSmilesQuery: (v: string) => void;
  setSimilarityThreshold: (v: number) => void;
  setSequenceQuery: (v: string) => void;
  setSequenceMinBitscore: (v: number) => void;
  setSequenceMinPident: (v: number) => void;
  setSequenceMinQcov: (v: number) => void;
  setSequenceTaskId: (id: string | null) => void;
  setDomainQueryTriggered: (v: boolean) => void;
  setChemicalQueryTriggered: (v: boolean) => void;
  setSequenceQueryTriggered: (v: boolean) => void;
  setDomainResultData: (data: QueryResultBgc[]) => void;
  setChemicalResultData: (data: QueryResultBgc[]) => void;
  setSequenceResultData: (data: QueryResultBgc[]) => void;
  computeIntersection: () => void;
  clearQuery: () => void;
}

function intersectResults(
  datasets: QueryResultBgc[][],
): { ids: number[]; data: QueryResultBgc[] } {
  if (datasets.length === 0) return { ids: [], data: [] };
  if (datasets.length === 1) {
    return { ids: datasets[0]!.map((r) => r.id), data: datasets[0]! };
  }

  // Find IDs present in ALL datasets
  const idSets = datasets.map((d) => new Set(d.map((r) => r.id)));
  const commonIds = [...idSets[0]!].filter((id) =>
    idSets.every((s) => s.has(id))
  );

  // Use the last dataset's entries for similarity_score (sequence > chemical > domain priority)
  const lastDataset = datasets[datasets.length - 1]!;
  const lastMap = new Map(lastDataset.map((r) => [r.id, r]));
  const data = commonIds
    .map((id) => lastMap.get(id))
    .filter((r): r is QueryResultBgc => r !== undefined);

  return { ids: commonIds, data };
}

export const useQueryStore = create<QueryState>((set, get) => ({
  domainConditions: [],
  logic: "and",
  similarBgcSourceId: null,
  resultBgcIds: [],
  resultBgcData: [],
  smilesQuery: "",
  similarityThreshold: 0.5,
  sequenceQuery: "",
  sequenceMinBitscore: 30,
  sequenceMinPident: 70,
  sequenceMinQcov: 70,
  sequenceTaskId: null,
  domainQueryTriggered: false,
  chemicalQueryTriggered: false,
  sequenceQueryTriggered: false,
  domainResultData: [],
  chemicalResultData: [],
  sequenceResultData: [],

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
  setSequenceQuery: (v) => set({ sequenceQuery: v }),
  setSequenceMinBitscore: (v) => set({ sequenceMinBitscore: v }),
  setSequenceMinPident: (v) => set({ sequenceMinPident: v }),
  setSequenceMinQcov: (v) => set({ sequenceMinQcov: v }),
  setSequenceTaskId: (id) => set({ sequenceTaskId: id }),
  setDomainQueryTriggered: (v) => set({ domainQueryTriggered: v }),
  setChemicalQueryTriggered: (v) => set({ chemicalQueryTriggered: v }),
  setSequenceQueryTriggered: (v) => set({ sequenceQueryTriggered: v }),
  setDomainResultData: (data) => set({ domainResultData: data }),
  setChemicalResultData: (data) => set({ chemicalResultData: data }),
  setSequenceResultData: (data) => set({ sequenceResultData: data }),
  computeIntersection: () => {
    const s = get();
    const activeDatasets: QueryResultBgc[][] = [];
    // Collect datasets in priority order (domain, chemical, sequence)
    // Sequence data comes last so its similarity_score wins in intersection
    if (s.domainResultData.length > 0) activeDatasets.push(s.domainResultData);
    if (s.chemicalResultData.length > 0)
      activeDatasets.push(s.chemicalResultData);
    if (s.sequenceResultData.length > 0)
      activeDatasets.push(s.sequenceResultData);

    const { ids, data } = intersectResults(activeDatasets);
    set({ resultBgcIds: ids, resultBgcData: data });
  },
  clearQuery: () =>
    set({
      domainConditions: [],
      logic: "and",
      similarBgcSourceId: null,
      resultBgcIds: [],
      resultBgcData: [],
      smilesQuery: "",
      similarityThreshold: 0.5,
      sequenceQuery: "",
      sequenceMinBitscore: 30,
      sequenceMinPident: 70,
      sequenceMinQcov: 70,
      sequenceTaskId: null,
      domainQueryTriggered: false,
      chemicalQueryTriggered: false,
      sequenceQueryTriggered: false,
      domainResultData: [],
      chemicalResultData: [],
      sequenceResultData: [],
    }),
}));
