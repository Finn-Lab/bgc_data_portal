import { useQuery } from "@tanstack/react-query";
import { fetchGenomeDetail } from "@/api/genomes";

export function useGenomeDetail(genomeId: number | null) {
  return useQuery({
    queryKey: ["genome-detail", genomeId],
    queryFn: () => fetchGenomeDetail(genomeId!),
    enabled: genomeId !== null,
  });
}
