import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useModeStore } from "@/stores/mode-store";
import { useFilterStore } from "@/stores/filter-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useQueryStore } from "@/stores/query-store";

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

    const sourceNamesParam = searchParams.get("source_names");
    if (sourceNamesParam) {
      useFilterStore.getState().setSourceNames(sourceNamesParam.split(",").filter(Boolean));
    }

    const detectorToolsParam = searchParams.get("detector_tools");
    if (detectorToolsParam) {
      useFilterStore.getState().setDetectorTools(detectorToolsParam.split(",").filter(Boolean));
    }

    const bgcClass = searchParams.get("bgc_class");
    if (bgcClass) useFilterStore.getState().setBgcClass(bgcClass);

    const search = searchParams.get("search");
    if (search) useFilterStore.getState().setSearch(search);

    const taxonomyPath = searchParams.get("taxonomy_path");
    if (taxonomyPath) useFilterStore.getState().setTaxonomyPath(taxonomyPath);

    const assemblyType = searchParams.get("assembly_type");
    if (assemblyType) useFilterStore.getState().setAssemblyType(assemblyType);

    const biomeLineage = searchParams.get("biome_lineage");
    if (biomeLineage) useFilterStore.getState().setBiomeLineage(biomeLineage);

    const assemblyId = searchParams.get("assembly");
    if (assemblyId) {
      useSelectionStore.getState().setActiveAssemblyId(Number(assemblyId));
    }

    // Auto-run query when redirected from landing page keyword search
    const autoRun = searchParams.get("auto_run");
    if (autoRun === "true") {
      const currentMode = useModeStore.getState().mode;
      if (currentMode === "query") {
        useQueryStore.getState().setDomainQueryTriggered(true);
      } else {
        useFilterStore.getState().runExploreQuery();
      }
      // Remove auto_run from URL so refreshing doesn't re-trigger
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("auto_run");
          return next;
        },
        { replace: true }
      );
    }
  }, [searchParams, setSearchParams]);

  // Write store changes to URL
  useEffect(() => {
    const unsubscribers = [
      useModeStore.subscribe((state) => updateUrl("mode", state.mode)),
      useFilterStore.subscribe((state) => {
        updateUrl("source_names", state.sourceNames.join(","));
        updateUrl("detector_tools", state.detectorTools.join(","));
        updateUrl("bgc_class", state.bgcClass);
        updateUrl("search", state.search);
        updateUrl("taxonomy_path", state.taxonomyPath);
        updateUrl("assembly_type", state.assemblyType);
        updateUrl("biome_lineage", state.biomeLineage);
      }),
      useSelectionStore.subscribe((state) => {
        updateUrl("assembly", state.activeAssemblyId?.toString() ?? "");
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
