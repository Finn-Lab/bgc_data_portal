import { apiGet } from "./client";

export interface DiscoveryStatsResponse {
  genomes: number;
  metagenomes: number;
  validated_bgcs: number;
  ibgcs: number;
  total_bgc_predictions: number;
  updated_at: string | null;
}

export function fetchDiscoveryStats() {
  return apiGet<DiscoveryStatsResponse>("/stats/");
}
