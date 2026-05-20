import { useQuery } from "@tanstack/react-query";
import { fetchIbgcCount } from "@/api/ibgcs";
import {
  appliedFiltersToApiParams,
  isAppliedFiltersEmpty,
  useDiscoveryStore,
} from "@/stores/discovery-store";

/**
 * Cheap COUNT against the iBGC filter surface.
 *
 * Fires only when the dashboard has an active scope (any chip applied or
 * a Run Query result). The roster + maps render an empty-state CTA when
 * the scope is empty, so we don't want to ping ``/ibgcs/count/`` either.
 *
 * The returned ``willSample`` flag drives the "Showing 5,000 of 1.2M
 * matches" banner; ``hasActiveScope`` is exposed so callers can gate
 * their own fetches off the same predicate.
 */
export function useIbgcCount() {
  const applied = useDiscoveryStore((s) => s.appliedFilters);
  const resultIbgcIds = useDiscoveryStore((s) => s.resultIbgcIds);
  const assetToken = useDiscoveryStore((s) => s.assetToken);

  // A loaded asset is itself an "active scope" — it forces the roster /
  // maps to render so the user can see their submitted iBGCs.
  const hasActiveScope =
    !isAppliedFiltersEmpty(applied) ||
    resultIbgcIds !== null ||
    assetToken !== null;

  const filterParams = appliedFiltersToApiParams(
    applied,
    resultIbgcIds,
    assetToken,
  );

  const query = useQuery({
    queryKey: ["ibgc-count", filterParams],
    queryFn: () => fetchIbgcCount(filterParams),
    enabled: hasActiveScope,
  });

  return {
    hasActiveScope,
    count: query.data?.exact_count ?? null,
    cap: query.data?.cap ?? null,
    willSample: query.data?.will_sample ?? false,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
