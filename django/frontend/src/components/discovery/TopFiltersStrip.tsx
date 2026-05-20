import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FilterPanel } from "@/components/filters/FilterPanel";
import { ShortlistDropdown } from "@/components/discovery/ShortlistDropdown";
import { useDiscoveryStats } from "@/hooks/use-discovery-stats";
import { useIbgcCount } from "@/hooks/use-ibgc-count";
import { useRunIbgcQuery } from "@/hooks/use-run-ibgc-query";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { Info, Loader2, Play, X } from "lucide-react";

/**
 * Top strip that replaces the v1 sidebar. Two rows:
 *   - meta row: DB-stats badges (left) + Clear/Run-Query actions (right)
 *   - filter row: chip-style filters (scrollable, max-h ≈ 20vh)
 */
export function TopFiltersStrip() {
  const { data: stats } = useDiscoveryStats();
  const { run, isRunning } = useRunIbgcQuery();
  const resultIbgcIds = useDiscoveryStore((s) => s.resultIbgcIds);
  const searchSource = useDiscoveryStore((s) => s.searchSource);
  const setQueryResult = useDiscoveryStore((s) => s.setQueryResult);

  const clearLabel = (() => {
    switch (searchSource) {
      case "sequence":
        return "Clear sequence";
      case "domain":
        return "Clear domain";
      case "domain_architecture":
        return "Clear architecture";
      case "similar_ibgc":
        return "Clear similar";
      case "chemical":
        return "Clear chemical";
      default:
        return "Clear query";
    }
  })();

  return (
    <Card className="mx-2 mt-2 mb-0 overflow-hidden p-0">
      <div className="flex items-center justify-between gap-3 border-b px-3 py-1.5">
        <DbStatsBadges stats={stats} />
        <div className="flex items-center gap-1">
          {resultIbgcIds !== null && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1 text-xs"
              onClick={() => setQueryResult(null, null, null, null, null, null)}
            >
              <X className="h-3 w-3" />
              {clearLabel} ({resultIbgcIds.length})
            </Button>
          )}
          <ShortlistDropdown />
          <Button
            size="sm"
            className="h-8 gap-1.5"
            data-tour="run-query"
            onClick={run}
            disabled={isRunning}
          >
            {isRunning ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            Run Query
          </Button>
        </div>
      </div>
      <div className="max-h-[20vh] overflow-y-auto px-3 py-2">
        <FilterPanel />
      </div>
      <ResultScopeBanner />
    </Card>
  );
}

/**
 * Inline banner under the filter strip that surfaces the active result
 * scope. Only renders when the dashboard has a scope set; stays silent on
 * the empty landing so the empty-state CTAs in the surfaces do the
 * talking.
 *
 * When the filter matches more than ``cap`` iBGCs, the banner warns the
 * user that the UMAP + Variables maps are showing a deterministic sample
 * so they can narrow further if needed.
 */
function ResultScopeBanner() {
  const { hasActiveScope, count, cap, willSample, isLoading } = useIbgcCount();
  if (!hasActiveScope) return null;
  if (isLoading) return null;
  if (count == null || cap == null) return null;

  const fmt = (n: number) => n.toLocaleString();
  return (
    <div
      className="flex items-center gap-2 border-t bg-muted/30 px-3 py-1.5 text-xs"
      data-testid="result-scope-banner"
    >
      <Info className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      {willSample ? (
        <span>
          <span className="font-semibold">{fmt(cap)}</span> of{" "}
          <span className="font-semibold">{fmt(count)}</span> matching iBGCs
          shown on the maps (deterministic sample). Narrow the filters to
          see all results.
        </span>
      ) : (
        <span className="text-muted-foreground">
          <span className="font-semibold text-foreground">{fmt(count)}</span>{" "}
          matching iBGC{count === 1 ? "" : "s"}.
        </span>
      )}
    </div>
  );
}

interface DbStatsBadgesProps {
  stats?: {
    genomes: number;
    metagenomes: number;
    validated_bgcs: number;
    ibgcs: number;
    total_bgc_predictions: number;
  };
}

function DbStatsBadges({ stats }: DbStatsBadgesProps) {
  const fmt = (n?: number) => (n == null ? "—" : n.toLocaleString());
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant="outline" className="h-6 font-mono text-[10px]">
        VALIDATED BGCS{" "}
        <span className="ml-1.5 font-semibold">
          {fmt(stats?.validated_bgcs)}
        </span>
      </Badge>
      <Badge variant="outline" className="h-6 font-mono text-[10px]">
        INTEGRATED BGCS{" "}
        <span className="ml-1.5 font-semibold">{fmt(stats?.ibgcs)}</span>
      </Badge>
      <Badge variant="outline" className="h-6 font-mono text-[10px]">
        PREDICTED BGCS{" "}
        <span className="ml-1.5 font-semibold">
          {fmt(stats?.total_bgc_predictions)}
        </span>
      </Badge>
      <Badge variant="outline" className="h-6 font-mono text-[10px]">
        GENOMES{" "}
        <span className="ml-1.5 font-semibold">{fmt(stats?.genomes)}</span>
      </Badge>
      <Badge variant="outline" className="h-6 font-mono text-[10px]">
        METAGENOMES{" "}
        <span className="ml-1.5 font-semibold">{fmt(stats?.metagenomes)}</span>
      </Badge>
    </div>
  );
}
