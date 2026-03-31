import { useQuery } from "@tanstack/react-query";
import { fetchBgcStats } from "@/api/bgcs";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";

export function useBgcStats() {
  const activeGenomeId = useSelectionStore((s) => s.activeGenomeId);
  const genomeShortlist = useShortlistStore((s) => s.genomes);

  const assemblyIds =
    genomeShortlist.length > 0
      ? genomeShortlist.map((g) => g.id)
      : activeGenomeId
        ? [activeGenomeId]
        : [];

  const assemblyIdsStr =
    assemblyIds.length > 0 ? assemblyIds.join(",") : undefined;

  const enabled = assemblyIds.length > 0;

  return useQuery({
    queryKey: ["bgc-stats", assemblyIdsStr],
    queryFn: () => fetchBgcStats({ assembly_ids: assemblyIdsStr }),
    enabled,
    staleTime: 30_000,
  });
}
