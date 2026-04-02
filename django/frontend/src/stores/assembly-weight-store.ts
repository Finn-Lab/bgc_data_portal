import { create } from "zustand";
import { GENOME_WEIGHT_DEFAULTS, type GenomeWeightParams } from "@/api/types";

interface GenomeWeightState extends GenomeWeightParams {
  setWeight: (key: keyof GenomeWeightParams, value: number) => void;
  resetDefaults: () => void;
}

export const useGenomeWeightStore = create<GenomeWeightState>((set) => ({
  ...GENOME_WEIGHT_DEFAULTS,
  setWeight: (key, value) => set({ [key]: value }),
  resetDefaults: () => set(GENOME_WEIGHT_DEFAULTS),
}));
