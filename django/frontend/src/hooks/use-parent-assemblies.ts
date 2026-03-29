import { useQuery } from "@tanstack/react-query";
import { fetchParentAssemblies } from "@/api/bgcs";

export function useParentAssemblies(bgcIds: number[]) {
  return useQuery({
    queryKey: ["parent-assemblies", bgcIds],
    queryFn: () => fetchParentAssemblies(bgcIds),
    enabled: bgcIds.length > 0,
  });
}
