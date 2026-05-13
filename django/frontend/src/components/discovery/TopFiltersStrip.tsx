import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FilterPanel } from "@/components/filters/FilterPanel";
import { useDiscoveryStats } from "@/hooks/use-discovery-stats";
import { useRunNrbQuery } from "@/hooks/use-run-nrb-query";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { Loader2, Play, X } from "lucide-react";

/**
 * Top strip that replaces the v1 sidebar. Hosts:
 *   - DB-stats badges (left)
 *   - Filter accordion (middle) — re-uses the existing FilterPanel until P2
 *     gets a dedicated NRB-filter form
 *   - Run Query button (bottom-right)
 *
 * Wired as a single Card so it visually anchors the top of the page.
 */
export function TopFiltersStrip() {
  const { data: stats } = useDiscoveryStats();
  const { run, isRunning } = useRunNrbQuery();
  const resultNrbIds = useDiscoveryStore((s) => s.resultNrbIds);
  const setQueryResult = useDiscoveryStore((s) => s.setQueryResult);

  return (
    <Card className="m-2 mb-0 p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch lg:justify-between">
        <DbStatsBadges stats={stats} />

        <div className="flex-1 lg:px-4">
          <FilterPanel />
        </div>

        <div className="flex flex-col items-end justify-end gap-1">
          {resultNrbIds !== null && (
            <Button
              variant="ghost"
              size="sm"
              className="gap-1 text-xs"
              onClick={() => setQueryResult(null, null)}
            >
              <X className="h-3 w-3" />
              Clear query ({resultNrbIds.length})
            </Button>
          )}
          <Button
            size="lg"
            className="gap-2"
            data-tour="run-query"
            onClick={run}
            disabled={isRunning}
          >
            {isRunning ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Run Query
          </Button>
        </div>
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
    <div className="flex flex-wrap items-center gap-2 lg:flex-col lg:items-start lg:gap-1">
      <Badge variant="outline" className="font-mono">
        Regions <span className="ml-2 font-semibold">{fmt(stats?.regions)}</span>
      </Badge>
      <Badge variant="outline" className="font-mono">
        BGCs{" "}
        <span className="ml-2 font-semibold">
          {fmt(stats?.total_bgc_predictions)}
        </span>
      </Badge>
      <Badge variant="outline" className="font-mono">
        Validated{" "}
        <span className="ml-2 font-semibold">{fmt(stats?.validated_bgcs)}</span>
      </Badge>
      <Badge variant="outline" className="font-mono">
        Genomes{" "}
        <span className="ml-2 font-semibold">{fmt(stats?.genomes)}</span>
      </Badge>
    </div>
  );
}
