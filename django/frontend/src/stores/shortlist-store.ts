import { create } from "zustand";
import { persist } from "zustand/middleware";

// Cap matches backend `MAX_SHORTLIST` in services/report.py; sized so a
// single "Add all to shortlist" action can fill the shortlist from a
// filtered roster in one shot.
export const MAX_SHORTLIST = 1000;

interface ShortlistItem {
  id: number;
  label: string;
}

interface ShortlistState {
  // ── BGC / iBGC shortlist (primary unit in v2) ────────────────────────────
  bgcs: ShortlistItem[];

  addBgc: (item: ShortlistItem) => boolean;
  /** Bulk add. Items already on the shortlist are silently kept; items
   *  beyond MAX_SHORTLIST are dropped. Returns counts so the caller can
   *  surface "added X, Y skipped" toasts. */
  addBgcsBulk: (items: ShortlistItem[]) => { added: number; skipped: number };
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
      addBgcsBulk: (items) => {
        const current = get().bgcs;
        const seen = new Set(current.map((b) => b.id));
        const remaining = Math.max(0, MAX_SHORTLIST - current.length);
        const accepted: ShortlistItem[] = [];
        let skipped = 0;
        for (const item of items) {
          if (seen.has(item.id)) continue;
          if (accepted.length >= remaining) {
            skipped += 1;
            continue;
          }
          accepted.push(item);
          seen.add(item.id);
        }
        if (accepted.length > 0) {
          set({ bgcs: [...current, ...accepted] });
        }
        return { added: accepted.length, skipped };
      },
      removeBgc: (id) =>
        set((s) => ({ bgcs: s.bgcs.filter((b) => b.id !== id) })),
      clearBgcs: () => set({ bgcs: [] }),
      replaceBgcs: (item) => set({ bgcs: [item] }),
    }),
    { name: "discovery-shortlists" }
  )
);
