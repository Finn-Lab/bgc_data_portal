import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useModeStore } from "@/stores/mode-store";
import { useFilterStore } from "@/stores/filter-store";
import { useSelectionStore } from "@/stores/selection-store";

export function useUrlSync() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialized = useRef(false);

  // Hydrate stores from URL on mount
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    const mode = searchParams.get("mode");
    if (mode === "explore" || mode === "query" || mode === "assess") {
      useModeStore.getState().setMode(mode);
    }

    const typeStrain = searchParams.get("type_strain_only");
    if (typeStrain === "true") {
      useFilterStore.getState().setTypeStrainOnly(true);
    }

    const bgcClass = searchParams.get("bgc_class");
    if (bgcClass) useFilterStore.getState().setBgcClass(bgcClass);

    const search = searchParams.get("search");
    if (search) useFilterStore.getState().setSearch(search);

    for (const rank of [
      "kingdom",
      "phylum",
      "class",
      "order",
      "family",
      "genus",
    ]) {
      const val = searchParams.get(`taxonomy_${rank}`);
      if (val) useFilterStore.getState().setTaxonomy(rank, val);
    }

    const genomeId = searchParams.get("genome");
    if (genomeId) {
      useSelectionStore.getState().setActiveGenomeId(Number(genomeId));
    }
  }, [searchParams]);

  // Write store changes to URL
  useEffect(() => {
    const unsubscribers = [
      useModeStore.subscribe((state) => updateUrl("mode", state.mode)),
      useFilterStore.subscribe((state) => {
        updateUrl("type_strain_only", state.typeStrainOnly ? "true" : "");
        updateUrl("bgc_class", state.bgcClass);
        updateUrl("search", state.search);
        updateUrl("taxonomy_kingdom", state.taxonomyKingdom);
        updateUrl("taxonomy_phylum", state.taxonomyPhylum);
        updateUrl("taxonomy_class", state.taxonomyClass);
        updateUrl("taxonomy_order", state.taxonomyOrder);
        updateUrl("taxonomy_family", state.taxonomyFamily);
        updateUrl("taxonomy_genus", state.taxonomyGenus);
      }),
      useSelectionStore.subscribe((state) => {
        updateUrl("genome", state.activeGenomeId?.toString() ?? "");
      }),
    ];

    return () => unsubscribers.forEach((unsub) => unsub());
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  function updateUrl(key: string, value: string) {
    clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value && value !== "query") {
            next.set(key, value);
          } else if (key !== "mode") {
            next.delete(key);
          } else if (value === "query") {
            next.delete(key);
          }
          return next;
        },
        { replace: true }
      );
    }, 300);
  }
}
