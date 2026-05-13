import { create } from "zustand";

// "assess" mode retired in v2 (P1.4b); kept as a permitted value so any
// persisted URL params don't crash, but the shell no longer renders it.
export type DashboardMode = "explore" | "query" | "assess";

interface ModeState {
  mode: DashboardMode;
  setMode: (mode: DashboardMode) => void;
}

export const useModeStore = create<ModeState>((set) => ({
  mode: "query",
  setMode: (mode) => set({ mode }),
}));
