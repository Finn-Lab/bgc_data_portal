import { create } from "zustand";
import { persist } from "zustand/middleware";

// v2 raised the cap from 20 → 100 so a single shortlist can drive a
// meaningful Report. Backend `MAX_SHORTLIST` in services/report.py matches.
export const MAX_SHORTLIST = 100;

interface ShortlistItem {
  id: number;
  label: string;
}

interface ShortlistState {
  // ── BGC / iBGC shortlist (primary unit in v2) ────────────────────────────
  bgcs: ShortlistItem[];

  addBgc: (item: ShortlistItem) => boolean;
  removeBgc: (id: number) => void;
  clearBgcs: () => void;
  replaceBgcs: (item: ShortlistItem) => void;

  // ── Assembly shortlist (deprecated; kept for legacy components until P4
  //    cleanup removes the sidebar). New surfaces should ignore this. ─────
  assemblies: ShortlistItem[];
  addAssembly: (item: ShortlistItem) => boolean;
  removeAssembly: (id: number) => void;
  clearAssemblies: () => void;
  replaceAssemblies: (item: ShortlistItem) => void;
}

export const useShortlistStore = create<ShortlistState>()(
  persist(
    (set, get) => ({
      assemblies: [],
      bgcs: [],

      addAssembly: (item) => {
        const current = get().assemblies;
        if (current.length >= MAX_SHORTLIST) return false;
        if (current.some((g) => g.id === item.id)) return true;
        set({ assemblies: [...current, item] });
        return true;
      },
      removeAssembly: (id) =>
        set((s) => ({ assemblies: s.assemblies.filter((g) => g.id !== id) })),
      clearAssemblies: () => set({ assemblies: [] }),
      replaceAssemblies: (item) => set({ assemblies: [item] }),

      addBgc: (item) => {
        const current = get().bgcs;
        if (current.length >= MAX_SHORTLIST) return false;
        if (current.some((b) => b.id === item.id)) return true;
        set({ bgcs: [...current, item] });
        return true;
      },
      removeBgc: (id) =>
        set((s) => ({ bgcs: s.bgcs.filter((b) => b.id !== id) })),
      clearBgcs: () => set({ bgcs: [] }),
      replaceBgcs: (item) => set({ bgcs: [item] }),
    }),
    { name: "discovery-shortlists" }
  )
);
