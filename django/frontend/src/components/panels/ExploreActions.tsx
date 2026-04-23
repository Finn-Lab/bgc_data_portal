import { Button } from "@/components/ui/button";
import { useFilterStore } from "@/stores/filter-store";
import { Play } from "lucide-react";
import { PlatformStats } from "@/components/panels/PlatformStats";

export function ExploreActions() {
  const filters = useFilterStore();

  const hasFilters =
    !!filters.bgcClass ||
    !!filters.taxonomyPath ||
    !!filters.biomeLineage ||
    !!filters.assemblyAccession ||
    !!filters.bgcAccession ||
    !!filters.search ||
    !!filters.assemblyType ||
    filters.sourceNames.length > 0 ||
    filters.detectorTools.length > 0 ||
    filters.chemontIds.length > 0;

  return (
    <div
      className="vf-card vf-card--brand vf-card--bordered flex items-center gap-3"
      style={{ padding: "0.75rem" }}
      data-tour="run-query"
    >
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          className="gap-1"
          onClick={() => filters.runExploreQuery()}
          disabled={!hasFilters}
        >
          <Play className="h-4 w-4" />
          Run Query
        </Button>
        {!hasFilters && (
          <span className="text-xs text-muted-foreground">
            Set filters to explore assemblies
          </span>
        )}
      </div>
      <PlatformStats />
    </div>
  );
}
