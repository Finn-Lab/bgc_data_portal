import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FilterPanel } from "@/components/filters/FilterPanel";
import { useDiscoveryStats } from "@/hooks/use-discovery-stats";
import { useRunNrbQuery } from "@/hooks/use-run-nrb-query";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { Loader2, Play, X } from "lucide-react";

/**
 * Top strip that replaces the v1 sidebar. Two rows:
 *   - meta row: DB-stats badges (left) + Clear/Run-Query actions (right)
 *   - filter row: chip-style filters (scrollable, max-h ≈ 20vh)
 */
export function TopFiltersStrip() {
  const { data: stats } = useDiscoveryStats();
  const { run, isRunning } = useRunNrbQuery();
  const resultNrbIds = useDiscoveryStore((s) => s.resultNrbIds);
  const setQueryResult = useDiscoveryStore((s) => s.setQueryResult);

  return (
    <Card className="mx-2 mt-2 mb-0 overflow-hidden p-0">
      <div className="flex items-center justify-between gap-3 border-b px-3 py-1.5">
        <DbStatsBadges stats={stats} />
        <div className="flex items-center gap-1">
          {resultNrbIds !== null && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1 text-xs"
              onClick={() => setQueryResult(null, null)}
            >
              <X className="h-3 w-3" />
              Clear query ({resultNrbIds.length})
            </Button>
          )}
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
    </Card>
  );
}

interface DbStatsBadgesProps {
  stats?: {
    genomes: number;
    metagenomes: number;
    validated_bgcs: number;
    regions: number;
    total_bgc_predictions: number;
  };
}

function DbStatsBadges({ stats }: DbStatsBadgesProps) {
  const fmt = (n?: number) => (n == null ? "—" : n.toLocaleString());
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant="outline" className="h-6 font-mono text-[10px]">
        Regions{" "}
        <span className="ml-1.5 font-semibold">{fmt(stats?.regions)}</span>
      </Badge>
      <Badge variant="outline" className="h-6 font-mono text-[10px]">
        BGCs{" "}
        <span className="ml-1.5 font-semibold">
          {fmt(stats?.total_bgc_predictions)}
        </span>
      </Badge>
      <Badge variant="outline" className="h-6 font-mono text-[10px]">
        Validated{" "}
        <span className="ml-1.5 font-semibold">
          {fmt(stats?.validated_bgcs)}
        </span>
      </Badge>
      <Badge variant="outline" className="h-6 font-mono text-[10px]">
        Genomes{" "}
        <span className="ml-1.5 font-semibold">{fmt(stats?.genomes)}</span>
      </Badge>
    </div>
  );
}
