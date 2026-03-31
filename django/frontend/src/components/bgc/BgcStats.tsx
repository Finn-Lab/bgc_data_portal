import { useMemo } from "react";
import Plot from "react-plotly.js";
import { useBgcStats } from "@/hooks/use-bgc-stats";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { StatsExportMenu } from "@/components/stats/StatsExportMenu";
import { exportBgcStats } from "@/api/exports";
import type { CoreDomain } from "@/api/types";

const BGC_CLASS_COLORS: Record<string, string> = {
  Polyketide: "#3b82f6",
  NRP: "#ef4444",
  RiPP: "#22c55e",
  Terpene: "#f97316",
  Saccharide: "#a855f7",
  Alkaloid: "#14b8a6",
  Other: "#6b7280",
};

export function BgcStats() {
  const { data, isLoading } = useBgcStats();

  if (isLoading) {
    return <Skeleton className="h-[280px] w-full" />;
  }

  if (!data || data.total_bgcs === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">
        No BGC data available
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Row 1: Core Domains + Score Boxplots + Completeness Pie */}
      <div className="grid grid-cols-3 gap-2">
        <div className="flex flex-col items-center justify-center">
          <CoreDomainsDisplay domains={data.core_domains} />
        </div>
        <div className="flex flex-col items-center">
          <ScoreBoxplots distributions={data.score_distributions} />
        </div>
        <div className="flex flex-col items-center">
          <CompletenessPie
            complete={data.complete_count}
            partial={data.partial_count}
          />
        </div>
      </div>

      {/* Row 2: NP Chemical Class Sunburst + BGC Class Pie */}
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col items-center">
          <NpClassSunburst nodes={data.np_class_sunburst} />
        </div>
        <div className="flex flex-col items-center">
          <BgcClassPie distribution={data.bgc_class_distribution} />
        </div>
      </div>
    </div>
  );
}

export function BgcStatsActions() {
  const activeGenomeId = useSelectionStore((s) => s.activeGenomeId);
  const genomeShortlist = useShortlistStore((s) => s.genomes);

  const assemblyIds =
    genomeShortlist.length > 0
      ? genomeShortlist.map((g) => g.id).join(",")
      : activeGenomeId
        ? String(activeGenomeId)
        : undefined;

  return (
    <StatsExportMenu
      onExport={(format) =>
        exportBgcStats({ assembly_ids: assemblyIds }, format)
      }
    />
  );
}

const PLOTLY_LAYOUT_BASE: Partial<Plotly.Layout> = {
  margin: { t: 20, b: 20, l: 30, r: 10 },
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  font: { size: 10, color: "#888" },
};

const PLOTLY_CONFIG: Partial<Plotly.Config> = {
  displayModeBar: false,
  responsive: true,
};

function CoreDomainsDisplay({ domains }: { domains: CoreDomain[] }) {
  if (domains.length === 0) {
    return (
      <div className="flex h-[200px] flex-col items-center justify-center text-xs text-muted-foreground">
        <div className="text-lg font-bold">0</div>
        <div>Core Domains (&gt;80%)</div>
      </div>
    );
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className="flex h-[200px] flex-col items-center justify-center gap-1 rounded-md border border-transparent hover:border-border hover:bg-muted/50 px-4 transition-colors cursor-pointer">
          <div className="text-3xl font-bold">{domains.length}</div>
          <div className="text-xs text-muted-foreground">
            Core Domains (&gt;80%)
          </div>
          <div className="text-[10px] text-muted-foreground">
            Click to view
          </div>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 max-h-60 overflow-auto">
        <div className="flex flex-col gap-1">
          <div className="text-sm font-medium mb-1">
            Domains in &gt;80% of BGCs
          </div>
          {domains.map((d) => (
            <div
              key={d.acc}
              className="flex items-center justify-between text-xs"
            >
              <span className="truncate mr-2">
                <Badge variant="outline" className="text-[10px] mr-1">
                  {d.acc}
                </Badge>
                {d.name}
              </span>
              <span className="shrink-0 text-muted-foreground">
                {d.bgc_count} ({(d.fraction * 100).toFixed(0)}%)
              </span>
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ScoreBoxplots({
  distributions,
}: {
  distributions: { label: string; values: number[] }[];
}) {
  if (distributions.length === 0) return <EmptyPlaceholder label="No score data" />;

  const traces: Plotly.Data[] = distributions.map((d) => ({
    type: "box" as const,
    y: d.values,
    name: d.label,
    boxpoints: false,
    marker: { color: "#3b82f6" },
  }));

  return (
    <Plot
      data={traces}
      layout={{
        ...PLOTLY_LAYOUT_BASE,
        width: 180,
        height: 200,
        title: { text: "Score Distributions", font: { size: 11 } },
        showlegend: false,
      }}
      config={PLOTLY_CONFIG}
    />
  );
}

function CompletenessPie({
  complete,
  partial,
}: {
  complete: number;
  partial: number;
}) {
  if (complete + partial === 0)
    return <EmptyPlaceholder label="No completeness data" />;

  return (
    <Plot
      data={[
        {
          type: "pie",
          labels: ["Complete", "Partial"],
          values: [complete, partial],
          marker: { colors: ["#22c55e", "#f97316"] },
          textinfo: "label+percent",
          hovertemplate: "<b>%{label}</b><br>Count: %{value}<extra></extra>",
        } as Plotly.Data,
      ]}
      layout={{
        ...PLOTLY_LAYOUT_BASE,
        width: 180,
        height: 200,
        title: { text: "Completeness", font: { size: 11 } },
        showlegend: false,
      }}
      config={PLOTLY_CONFIG}
    />
  );
}

function NpClassSunburst({
  nodes,
}: {
  nodes: { id: string; label: string; parent: string; count: number }[];
}) {
  if (nodes.length === 0)
    return <EmptyPlaceholder label="No NP class data" />;

  return (
    <Plot
      data={[
        {
          type: "sunburst",
          ids: nodes.map((n) => n.id),
          labels: nodes.map((n) => n.label),
          parents: nodes.map((n) => n.parent),
          values: nodes.map((n) => n.count),
          branchvalues: "total",
          hovertemplate: "<b>%{label}</b><br>Count: %{value}<extra></extra>",
        } as Plotly.Data,
      ]}
      layout={{
        ...PLOTLY_LAYOUT_BASE,
        width: 180,
        height: 200,
        title: { text: "NP Chemical Class", font: { size: 11 } },
      }}
      config={PLOTLY_CONFIG}
    />
  );
}

function BgcClassPie({
  distribution,
}: {
  distribution: { name: string; count: number }[];
}) {
  if (distribution.length === 0)
    return <EmptyPlaceholder label="No BGC class data" />;

  const colors = distribution.map(
    (d) => BGC_CLASS_COLORS[d.name] || "#6b7280"
  );

  return (
    <Plot
      data={[
        {
          type: "pie",
          labels: distribution.map((d) => d.name),
          values: distribution.map((d) => d.count),
          marker: { colors },
          textinfo: "label+percent",
          hovertemplate: "<b>%{label}</b><br>Count: %{value}<extra></extra>",
        } as Plotly.Data,
      ]}
      layout={{
        ...PLOTLY_LAYOUT_BASE,
        width: 180,
        height: 200,
        title: { text: "BGC Classes", font: { size: 11 } },
        showlegend: false,
      }}
      config={PLOTLY_CONFIG}
    />
  );
}

function EmptyPlaceholder({ label }: { label: string }) {
  return (
    <div className="flex h-[200px] w-[180px] items-center justify-center text-xs text-muted-foreground">
      {label}
    </div>
  );
}
