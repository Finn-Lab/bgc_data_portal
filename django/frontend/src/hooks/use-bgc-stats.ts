import { useQuery } from "@tanstack/react-query";
import { fetchBgcStats } from "@/api/bgcs";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";

export function useBgcStats(options?: {
  assemblyIdOverride?: number;
  bgcIds?: number[];
}) {
  const { assemblyIdOverride, bgcIds } = options ?? {};
  const activeGenomeId = useSelectionStore((s) => s.activeGenomeId);
  const genomeShortlist = useShortlistStore((s) => s.genomes);

  const hasBgcIds = bgcIds != null && bgcIds.length > 0;

  const assemblyIds = assemblyIdOverride
    ? [assemblyIdOverride]
    : genomeShortlist.length > 0
      ? genomeShortlist.map((g) => g.id)
      : activeGenomeId
        ? [activeGenomeId]
        : [];

  const bgcIdsStr = hasBgcIds ? bgcIds.join(",") : undefined;
  const assemblyIdsStr =
    !hasBgcIds && assemblyIds.length > 0 ? assemblyIds.join(",") : undefined;

  const enabled = hasBgcIds || assemblyIds.length > 0;

  return useQuery({
    queryKey: ["bgc-stats", bgcIdsStr ?? assemblyIdsStr],
    queryFn: () =>
      fetchBgcStats({
        bgc_ids: bgcIdsStr,
        assembly_ids: bgcIdsStr ? undefined : assemblyIdsStr,
      }),
    enabled,
    staleTime: 30_000,
  });
}
