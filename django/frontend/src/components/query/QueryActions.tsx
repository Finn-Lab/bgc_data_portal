import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useQueryStore } from "@/stores/query-store";
import { useFilterStore } from "@/stores/filter-store";
import { useDomainQuery } from "@/hooks/use-domain-query";
import { useChemicalQuery } from "@/hooks/use-chemical-query";
import { useSequenceQuery } from "@/hooks/use-sequence-query";
import { useSimilarBgcQuery } from "@/hooks/use-similar-bgc-query";
import { Play, Loader2 } from "lucide-react";
import { PlatformStats } from "@/components/panels/PlatformStats";

export function QueryActions() {
  const similarBgcSourceId = useQueryStore((s) => s.similarBgcSourceId);
  const conditions = useQueryStore((s) => s.domainConditions);
  const smilesQuery = useQueryStore((s) => s.smilesQuery);
  const sequenceQuery = useQueryStore((s) => s.sequenceQuery);
  const filters = useFilterStore();

  const {
    runQuery: runDomainQuery,
    isFetching: domainFetching,
    hasConditions,
  } = useDomainQuery();
  const {
    runQuery: runChemicalQuery,
    isFetching: chemicalFetching,
  } = useChemicalQuery();
  const {
    runQuery: runSequenceQuery,
    isFetching: sequenceFetching,
  } = useSequenceQuery();
  const { isFetching: similarFetching } = useSimilarBgcQuery();

  const isFetching =
    domainFetching || chemicalFetching || sequenceFetching || similarFetching;
  const hasSmilesQuery = smilesQuery.trim().length > 0;
  const hasSequenceQuery =
    sequenceQuery.trim().length > 0 && sequenceQuery.trim().length <= 5000;
  const hasFilters =
    hasConditions ||
    hasSmilesQuery ||
    hasSequenceQuery ||
    !!filters.bgcClass ||
    !!filters.taxonomyPath ||
    !!filters.biomeLineage ||
    !!filters.assemblyAccession ||
    !!filters.bgcAccession ||
    !!filters.search ||
    filters.sourceNames.length > 0 ||
    filters.detectorTools.length > 0 ||
    filters.chemontIds.length > 0;

  const handleRunQuery = () => {
    if (hasSequenceQuery) runSequenceQuery();
    if (hasSmilesQuery) runChemicalQuery();
    if (hasConditions) runDomainQuery();
    // If only filters are set (no domains, SMILES, or sequence), run domain query
    // which will apply filters even with empty domain list
    if (!hasSmilesQuery && !hasConditions && !hasSequenceQuery) runDomainQuery();
  };

  // Build summary of active criteria
  const summaryParts: string[] = [];
  if (hasConditions)
    summaryParts.push(
      `${conditions.length} domain${conditions.length !== 1 ? "s" : ""}`
    );
  if (hasSequenceQuery) summaryParts.push("sequence query");
  if (hasSmilesQuery) summaryParts.push("SMILES query");

  return (
    <div
      className="vf-card vf-card--brand vf-card--bordered flex items-center gap-3"
      style={{ padding: "0.75rem" }}
    >
      {similarBgcSourceId ? (
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs">
            Similar BGC search
          </Badge>
          <span className="text-xs text-muted-foreground">
            Source: BGC #{similarBgcSourceId}
          </span>
          {isFetching && <Loader2 className="h-4 w-4 animate-spin" />}
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            className="gap-1"
            onClick={handleRunQuery}
            disabled={!hasFilters || isFetching}
          >
            {isFetching ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Run Query
          </Button>
          {summaryParts.length > 0 && (
            <span className="text-xs text-muted-foreground">
              {summaryParts.join(" + ")}
            </span>
          )}
          {!hasFilters && (
            <span className="text-xs text-muted-foreground">
              Set filters, domains, a sequence, or a SMILES query to search
            </span>
          )}
        </div>
      )}
      <PlatformStats />
    </div>
  );
}
