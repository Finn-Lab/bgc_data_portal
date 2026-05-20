import { useDiscoveryStore } from "@/stores/discovery-store";
import { CompactIbgcDetail } from "./CompactIbgcDetail";

export function CompareDetailSlot() {
  const compareIbgcId = useDiscoveryStore((s) => s.compareIbgcId);
  return <CompactIbgcDetail ibgcId={compareIbgcId} variant="compare" />;
}
