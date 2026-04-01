import { create } from "zustand";

export type DashboardMode = "explore" | "query" | "assess";

interface ModeState {
  mode: DashboardMode;
  setMode: (mode: DashboardMode) => void;
}

export const useModeStore = create<ModeState>((set) => ({
  mode: "query",
  setMode: (mode) => set({ mode }),
}));
