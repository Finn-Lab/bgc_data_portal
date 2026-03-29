import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useQueryStore } from "@/stores/query-store";
import { useFilterStore } from "@/stores/filter-store";
import { useDomainQuery } from "@/hooks/use-domain-query";
import { useChemicalQuery } from "@/hooks/use-chemical-query";
import { useSimilarBgcQuery } from "@/hooks/use-similar-bgc-query";
import { Play, Loader2 } from "lucide-react";

export function QueryActions() {
  const similarBgcSourceId = useQueryStore((s) => s.similarBgcSourceId);
  const conditions = useQueryStore((s) => s.domainConditions);
  const smilesQuery = useQueryStore((s) => s.smilesQuery);
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
  const { isFetching: similarFetching } = useSimilarBgcQuery();

  const isFetching = domainFetching || chemicalFetching || similarFetching;
  const hasSmilesQuery = smilesQuery.trim().length > 0;
  const hasFilters =
    hasConditions ||
    hasSmilesQuery ||
    !!filters.bgcClass ||
    !!filters.taxonomyKingdom ||
    !!filters.taxonomyPhylum ||
    !!filters.taxonomyClass ||
    !!filters.taxonomyOrder ||
    !!filters.taxonomyFamily ||
    !!filters.taxonomyGenus ||
    !!filters.biomeLineage ||
    !!filters.assemblyAccession ||
    !!filters.bgcAccession ||
    !!filters.search ||
    filters.typeStrainOnly;

  const handleRunQuery = () => {
    if (hasSmilesQuery) runChemicalQuery();
    if (hasConditions) runDomainQuery();
    // If only filters are set (no domains or SMILES), run domain query
    // which will apply filters even with empty domain list
    if (!hasSmilesQuery && !hasConditions) runDomainQuery();
  };

  // Build summary of active criteria
  const summaryParts: string[] = [];
  if (hasConditions)
    summaryParts.push(
      `${conditions.length} domain${conditions.length !== 1 ? "s" : ""}`
    );
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
              Set filters, domains, or a SMILES query to search
            </span>
          )}
        </div>
      )}
    </div>
  );
}
