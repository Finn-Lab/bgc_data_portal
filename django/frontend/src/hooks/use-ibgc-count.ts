import { useQuery } from "@tanstack/react-query";
import { fetchNrbCount } from "@/api/nrbs";
import {
  appliedFiltersToApiParams,
  isAppliedFiltersEmpty,
  useDiscoveryStore,
} from "@/stores/discovery-store";

/**
 * Cheap COUNT against the NRB filter surface.
 *
 * Fires only when the dashboard has an active scope (any chip applied or
 * a Run Query result). The roster + maps render an empty-state CTA when
 * the scope is empty, so we don't want to ping ``/nrbs/count/`` either.
 *
 * The returned ``willSample`` flag drives the "Showing 5,000 of 1.2M
 * matches" banner; ``hasActiveScope`` is exposed so callers can gate
 * their own fetches off the same predicate.
 */
export function useNrbCount() {
  const applied = useDiscoveryStore((s) => s.appliedFilters);
  const resultNrbIds = useDiscoveryStore((s) => s.resultNrbIds);
  const assetToken = useDiscoveryStore((s) => s.assetToken);

  // A loaded asset is itself an "active scope" — it forces the roster /
  // maps to render so the user can see their submitted NRBs.
  const hasActiveScope =
    !isAppliedFiltersEmpty(applied) ||
    resultNrbIds !== null ||
    assetToken !== null;

  const filterParams = appliedFiltersToApiParams(
    applied,
    resultNrbIds,
    assetToken,
  );

  const query = useQuery({
    queryKey: ["nrb-count", filterParams],
    queryFn: () => fetchNrbCount(filterParams),
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
