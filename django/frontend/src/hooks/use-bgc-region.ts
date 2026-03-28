import { useQuery } from "@tanstack/react-query";
import { fetchBgcRegion } from "@/api/bgcs";

export function useBgcRegion(bgcId: number | null) {
  return useQuery({
    queryKey: ["bgc-region", bgcId],
    queryFn: () => fetchBgcRegion(bgcId!),
    enabled: bgcId !== null,
  });
}
