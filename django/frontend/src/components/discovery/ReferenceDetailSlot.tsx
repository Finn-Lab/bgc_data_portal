import { useDiscoveryStore } from "@/stores/discovery-store";
import { CompactIbgcDetail } from "./CompactIbgcDetail";

export function ReferenceDetailSlot() {
  const referenceIbgcId = useDiscoveryStore((s) => s.referenceIbgcId);
  return <CompactIbgcDetail ibgcId={referenceIbgcId} variant="reference" />;
}
