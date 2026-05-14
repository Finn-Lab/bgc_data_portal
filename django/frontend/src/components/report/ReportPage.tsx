import { Fragment, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import Plot from "react-plotly.js";
import { useReport, useReportSnapshot } from "@/hooks/use-report";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Loader2 } from "lucide-react";
import { ReportDownloadButtons } from "./ReportDownloadButtons";
import type {
  CategoryCount,
  DomainCompositionSummary,
  DomainGoslimMatrix,
  GcfDistributionEntry,
  LengthBucket,
  ReportAssemblyRow,
  ReportNrbRow,
  ReportPayload,
  ReportScoreDistribution,
  SunburstNode,
} from "@/api/types";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/**
 * Shortlist Report page (route: ``/report``).
 *
 * URL state:
 *   - ``?token=<sha>`` — render cached payload by token.
 *   - ``?nrbs=1,2,3`` — POST snapshot first, then redirect/render with token.
 *
 * Both forms are accepted so the Generate-Report button in the dashboard
 * header can choose between sharing a stable token URL vs. opening a fresh
 * snapshot when the cache may have expired.
 */
export function ReportPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const token = searchParams.get("token");
  const nrbsParam = searchParams.get("nrbs");

  const snapshot = useReportSnapshot();
  const { data, isLoading, isError, error } = useReport(token);

  // If only ``?nrbs=`` was supplied (or token expired), mint a token from
  // the list and update the URL so the user can share/reload it.
  useEffect(() => {
    if (token) return;
    if (!nrbsParam) return;
    const ids = nrbsParam
      .split(",")
      .map((s) => parseInt(s, 10))
      .filter((n) => Number.isFinite(n));
    if (ids.length === 0) return;
    snapshot.mutate(ids, {
      onSuccess: (resp) => {
        setSearchParams({ token: resp.token }, { replace: true });
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, nrbsParam]);

  if (!token && !nrbsParam) {
    return (
      <PageShell>
        <p className="text-muted-foreground">
          Open this page from the Discovery dashboard via{" "}
          <span className="font-mono">Generate Report</span>, or pass a token
          via <span className="font-mono">?token=…</span> in the URL.
        </p>
      </PageShell>
    );
  }

  if (isLoading || snapshot.isPending) {
    return (
      <PageShell>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          {snapshot.isPending ? "Materialising report…" : "Loading report…"}
        </div>
      </PageShell>
    );
  }

  if (isError) {
    return (
      <PageShell>
        <p className="text-destructive">
          {(error as Error)?.message ?? "Failed to load report"}
        </p>
      </PageShell>
    );
  }

  if (!data) return <PageShell />;

  return (
    <PageShell>
      <ReportBody payload={data} />
    </PageShell>
  );
}

function PageShell({ children }: { children?: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background p-6">
      <div className="mx-auto max-w-7xl">{children}</div>
    </div>
  );
}

function ReportBody({ payload }: { payload: ReportPayload }) {
  return (
    <div data-report-root className="space-y-4">
      <ReportHeader payload={payload} />
      <NrbResultsSection rows={payload.nrb_rows} />
      <BgcStatsSection payload={payload} />
      <TaxonomySunburstSection nodes={payload.taxonomy_sunburst} />
      <AssemblyRosterSection rows={payload.assembly_rows} />
      <AssemblyStatsSection stats={payload.assembly_stats} />
    </div>
  );
}

function TaxonomySunburstSection({ nodes }: { nodes: SunburstNode[] }) {
  if (!nodes || nodes.length === 0) return null;
  return (
    <Card>
      <CardHeader className="p-4">
        <CardTitle className="text-base">Taxonomy</CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        <Plot
          data={[
            {
              type: "sunburst",
              ids: nodes.map((n) => n.id),
              labels: nodes.map((n) => n.label),
              parents: nodes.map((n) => n.parent),
              values: nodes.map((n) => n.count),
              branchvalues: "total",
              hovertemplate:
                "<b>%{label}</b><br>%{value} NRB(s)<extra></extra>",
            },
          ]}
          layout={{
            autosize: true,
            height: 420,
            margin: { l: 8, r: 8, t: 8, b: 8 },
          }}
          useResizeHandler
          style={{ width: "100%" }}
          config={{ displayModeBar: false }}
        />
      </CardContent>
    </Card>
  );
}

function ReportHeader({ payload }: { payload: ReportPayload }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4 p-4">
        <div>
          <h1 className="text-2xl font-semibold">BGC Shortlist Report</h1>
          <p className="text-xs text-muted-foreground">
            {payload.n_nrbs} NRB(s) · {payload.n_assemblies} assembly(ies)
          </p>
        </div>
        <ReportDownloadButtons
          token={payload.token}
          label={`${payload.n_nrbs} NRBs`}
        />
      </CardHeader>
    </Card>
  );
}

// ── NRB results table ──────────────────────────────────────────────────────

function NrbResultsSection({ rows }: { rows: ReportNrbRow[] }) {
  return (
    <Card>
      <CardHeader className="p-4">
        <CardTitle className="text-base">NRB Results</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="max-h-[420px]">
          <Table>
            <TableHeader className="sticky top-0 bg-card z-10">
              <TableRow>
                <TableHead>NRB</TableHead>
                <TableHead>Assembly</TableHead>
                <TableHead>Organism</TableHead>
                <TableHead>Phylum</TableHead>
                <TableHead>Biome</TableHead>
                <TableHead className="text-right">Size (kb)</TableHead>
                <TableHead className="text-right">Novelty</TableHead>
                <TableHead className="text-right">Dom. nov.</TableHead>
                <TableHead>GCF</TableHead>
                <TableHead>Sources</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono">
                    {r.label}
                    {r.is_validated && (
                      <Badge variant="default" className="ml-1 text-[10px]">
                        MIBiG
                      </Badge>
                    )}
                    {r.is_partial && (
                      <Badge variant="outline" className="ml-1 text-[10px]">
                        partial
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {r.parent_assembly_accession ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs">
                    {r.organism_name ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs">
                    {r.taxonomy_phylum ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs">{r.biome_path || "—"}</TableCell>
                  <TableCell className="text-right">
                    {r.size_kb.toFixed(1)}
                  </TableCell>
                  <TableCell className="text-right">
                    {fmt(r.novelty_score)}
                  </TableCell>
                  <TableCell className="text-right">
                    {fmt(r.domain_novelty)}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {r.classification_path || "—"}
                  </TableCell>
                  <TableCell className="text-xs">
                    {r.source_tools.join(", ")}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

// ── BGC stats (multi-panel grid) ───────────────────────────────────────────

function BgcStatsSection({ payload }: { payload: ReportPayload }) {
  return (
    <Card>
      <CardHeader className="p-4">
        <CardTitle className="text-base">BGC Stats</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
        <DomainCompositionPanel composition={payload.domain_composition} />
        <DomainGoslimHeatmapPanel matrix={payload.domain_goslim_matrix} />
        <GcfDistributionPanel rows={payload.gcf_distribution} />
        <ScoreDistributionPanel distributions={payload.score_distributions} />
        <CompletenessPanel rows={payload.completeness_pie} />
        <BgcClassPanel rows={payload.bgc_class_pie} />
        <LengthHistogramPanel rows={payload.length_histogram} />
        <PredictorPanel rows={payload.predictor_distribution} />
        <SourceDistributionPanel rows={payload.source_distribution} />
      </CardContent>
    </Card>
  );
}

function SourceDistributionPanel({ rows }: { rows: CategoryCount[] }) {
  return (
    <PanelCard title="Source distribution (NRBs per collection)">
      <Plot
        data={[
          {
            type: "bar",
            orientation: "h",
            x: rows.map((r) => r.count),
            y: rows.map((r) => r.name),
            marker: { color: "#a855f7" },
          },
        ]}
        layout={{
          autosize: true,
          height: 240,
          margin: { l: 140, r: 16, t: 8, b: 30 },
          xaxis: { title: { text: "NRBs" } },
          yaxis: { automargin: true, tickfont: { size: 10 } },
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false }}
      />
    </PanelCard>
  );
}

function DomainCompositionPanel({
  composition,
}: {
  composition: DomainCompositionSummary;
}) {
  const total = composition.total_unique || 1;
  const corePct = (composition.core_count / total) * 100;
  const varPct = (composition.variable_count / total) * 100;
  const rarePct = (composition.rare_count / total) * 100;
  return (
    <PanelCard title="Domain composition">
      <div className="mb-2 flex h-6 w-full overflow-hidden rounded border">
        <div
          className="bg-emerald-500 text-[10px] text-white"
          style={{ width: `${corePct}%` }}
          title={`Core (>${80}%): ${composition.core_count}`}
        >
          {corePct > 6 && `${composition.core_count} core`}
        </div>
        <div
          className="bg-amber-500 text-[10px] text-white"
          style={{ width: `${varPct}%` }}
          title={`Variable (40–80%): ${composition.variable_count}`}
        >
          {varPct > 6 && `${composition.variable_count} var`}
        </div>
        <div
          className="bg-slate-400 text-[10px] text-white"
          style={{ width: `${rarePct}%` }}
          title={`Rare (<40%): ${composition.rare_count}`}
        >
          {rarePct > 6 && `${composition.rare_count} rare`}
        </div>
      </div>
      <ScrollArea className="h-48 rounded border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Domain</TableHead>
              <TableHead className="text-right">NRBs</TableHead>
              <TableHead className="text-right">Fraction</TableHead>
              <TableHead>Tier</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {composition.rows.map((d) => (
              <TableRow key={d.domain_acc}>
                <TableCell className="font-mono text-xs">
                  {d.domain_acc}
                  {d.domain_name && (
                    <span className="ml-1 text-muted-foreground">
                      · {d.domain_name}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right">{d.nrb_count}</TableCell>
                <TableCell className="text-right">
                  {(d.fraction * 100).toFixed(1)}%
                </TableCell>
                <TableCell>
                  <Badge
                    variant={
                      d.tier === "core"
                        ? "default"
                        : d.tier === "variable"
                        ? "secondary"
                        : "outline"
                    }
                    className="text-[10px]"
                  >
                    {d.tier}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </ScrollArea>
    </PanelCard>
  );
}

const TIER_LABEL: Record<string, string> = {
  core: "CORE",
  variable: "Variable",
  rare: "RARE",
};

const TIER_COLOR: Record<string, [number, number, number]> = {
  // RGB triples for cell shading. Saturation scales with count vs. tier max.
  core: [16, 185, 129], // emerald-500
  variable: [245, 158, 11], // amber-500
  rare: [148, 163, 184], // slate-400
};

function cellBackground(rgb: [number, number, number], intensity: number): string {
  // Intensity in [0, 1]; 0 → near-white, 1 → full tier color.
  const i = Math.max(0.06, Math.min(1, intensity));
  const [r, g, b] = rgb;
  const mix = (v: number) => Math.round(255 - (255 - v) * i);
  return `rgb(${mix(r)}, ${mix(g)}, ${mix(b)})`;
}

function DomainGoslimHeatmapPanel({ matrix }: { matrix: DomainGoslimMatrix }) {
  const cellByKey = useMemo(() => {
    const m = new Map<string, DomainGoslimMatrix["cells"][number]>();
    for (const c of matrix.cells) m.set(`${c.category}::${c.tier}`, c);
    return m;
  }, [matrix.cells]);

  const tierMaxCount = useMemo(() => {
    const out: Record<string, number> = {};
    for (const t of matrix.tiers) {
      let max = 0;
      for (const c of matrix.categories) {
        const cell = cellByKey.get(`${c}::${t}`);
        if (cell && cell.count > max) max = cell.count;
      }
      out[t] = max || 1;
    }
    return out;
  }, [matrix.tiers, matrix.categories, cellByKey]);

  if (matrix.categories.length === 0) {
    return (
      <PanelCard title="Domain composition × GO slim">
        <p className="text-xs text-muted-foreground">
          No GO slim data available for this shortlist.
        </p>
      </PanelCard>
    );
  }

  return (
    <PanelCard title="Domain composition × GO slim">
      <TooltipProvider delayDuration={100}>
        <div className="overflow-x-auto">
          <div
            className="grid gap-px"
            style={{
              gridTemplateColumns: `minmax(80px, auto) repeat(${matrix.categories.length}, minmax(40px, 1fr))`,
            }}
          >
            {/* Header row — vertical labels so long GO slim names fit */}
            <div className="h-32" />
            {matrix.categories.map((cat) => (
              <div
                key={`hdr-${cat}`}
                className="flex h-32 items-end justify-center pb-1"
                title={cat}
              >
                <span
                  className="whitespace-nowrap text-[10px] font-medium text-muted-foreground"
                  style={{
                    writingMode: "vertical-rl",
                    transform: "rotate(180deg)",
                  }}
                >
                  {cat}
                </span>
              </div>
            ))}
            {/* Tier rows */}
            {matrix.tiers.map((tier) => (
              <Fragment key={`row-${tier}`}>
                <div className="flex items-center justify-end pr-2 text-[10px] font-medium">
                  {TIER_LABEL[tier] ?? tier}
                </div>
                {matrix.categories.map((cat) => {
                  const cell = cellByKey.get(`${cat}::${tier}`);
                  const count = cell?.count ?? 0;
                  const intensity = count / (tierMaxCount[tier] || 1);
                  const bg = cellBackground(
                    TIER_COLOR[tier] ?? [148, 163, 184],
                    intensity,
                  );
                  const textColor =
                    intensity > 0.55 ? "text-white" : "text-foreground";
                  return (
                    <Tooltip key={`${cat}-${tier}`}>
                      <TooltipTrigger asChild>
                        <div
                          className={`flex h-7 cursor-default items-center justify-center text-[10px] ${textColor}`}
                          style={{ backgroundColor: bg }}
                        >
                          {count > 0 ? count : ""}
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs text-xs">
                        <div className="mb-1 font-semibold">
                          {cat} · {TIER_LABEL[tier] ?? tier}
                        </div>
                        {count === 0 ? (
                          <div className="text-muted-foreground">
                            No domains
                          </div>
                        ) : (
                          <div className="space-y-0.5">
                            {(cell?.domains ?? []).slice(0, 20).map((d) => (
                              <div key={d.domain_acc}>
                                <strong>{d.domain_acc}</strong>
                                {d.domain_name && <> — {d.domain_name}</>}
                                {d.domain_description && (
                                  <div className="text-[10px] text-muted-foreground">
                                    {d.domain_description}
                                  </div>
                                )}
                              </div>
                            ))}
                            {(cell?.domains?.length ?? 0) > 20 && (
                              <div className="text-[10px] italic text-muted-foreground">
                                …and {(cell?.domains?.length ?? 0) - 20} more
                              </div>
                            )}
                          </div>
                        )}
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </Fragment>
            ))}
          </div>
        </div>
      </TooltipProvider>
    </PanelCard>
  );
}

function GcfDistributionPanel({ rows }: { rows: GcfDistributionEntry[] }) {
  const top = rows.slice(0, 20);
  return (
    <PanelCard title="GCF distribution (top 20)">
      <Plot
        data={[
          {
            type: "bar",
            orientation: "h",
            x: top.map((r) => r.nrb_count),
            y: top.map((r) => r.classification_path || "(unclassified)"),
            marker: { color: "#3b82f6" },
          },
        ]}
        layout={{
          autosize: true,
          height: 280,
          margin: { l: 160, r: 16, t: 8, b: 30 },
          xaxis: { title: { text: "NRBs" } },
          yaxis: { automargin: true, tickfont: { size: 10 } },
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false }}
      />
    </PanelCard>
  );
}

function ScoreDistributionPanel({
  distributions,
}: {
  distributions: ReportScoreDistribution[];
}) {
  return (
    <PanelCard title="Score distributions">
      <Plot
        data={distributions.map((d) => ({
          type: "histogram",
          x: d.values,
          name: d.label,
          opacity: 0.6,
          xbins: { start: 0, end: 1, size: 0.05 },
        }))}
        layout={{
          autosize: true,
          height: 240,
          margin: { l: 40, r: 16, t: 8, b: 30 },
          barmode: "overlay",
          xaxis: { title: { text: "Score" }, range: [0, 1] },
          yaxis: { title: { text: "NRBs" } },
          legend: { orientation: "h", y: -0.2 },
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false }}
      />
    </PanelCard>
  );
}

function CompletenessPanel({ rows }: { rows: CategoryCount[] }) {
  return (
    <PanelCard title="Completeness">
      <Plot
        data={[
          {
            type: "pie",
            labels: rows.map((r) => r.name),
            values: rows.map((r) => r.count),
            hole: 0.4,
            textinfo: "label+percent",
          },
        ]}
        layout={{
          autosize: true,
          height: 240,
          margin: { l: 16, r: 16, t: 16, b: 16 },
          showlegend: false,
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false }}
      />
    </PanelCard>
  );
}

function BgcClassPanel({ rows }: { rows: CategoryCount[] }) {
  return (
    <PanelCard title="BGC classes">
      <Plot
        data={[
          {
            type: "pie",
            labels: rows.map((r) => r.name),
            values: rows.map((r) => r.count),
            hole: 0.4,
            textinfo: "label+percent",
          },
        ]}
        layout={{
          autosize: true,
          height: 240,
          margin: { l: 16, r: 16, t: 16, b: 16 },
          showlegend: false,
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false }}
      />
    </PanelCard>
  );
}

function LengthHistogramPanel({ rows }: { rows: LengthBucket[] }) {
  return (
    <PanelCard title="Length distribution">
      <Plot
        data={[
          {
            type: "bar",
            x: rows.map((r) => r.label),
            y: rows.map((r) => r.count),
            marker: { color: "#6366f1" },
          },
        ]}
        layout={{
          autosize: true,
          height: 240,
          margin: { l: 40, r: 16, t: 8, b: 36 },
          xaxis: { title: { text: "kb" } },
          yaxis: { title: { text: "NRBs" } },
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false }}
      />
    </PanelCard>
  );
}

function PredictorPanel({ rows }: { rows: CategoryCount[] }) {
  return (
    <PanelCard title="Predictor distribution">
      <Plot
        data={[
          {
            type: "bar",
            x: rows.map((r) => r.name),
            y: rows.map((r) => r.count),
            marker: { color: "#10b981" },
          },
        ]}
        layout={{
          autosize: true,
          height: 240,
          margin: { l: 40, r: 16, t: 8, b: 36 },
          yaxis: { title: { text: "Hits" } },
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false }}
      />
    </PanelCard>
  );
}

function PanelCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="p-3">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="p-3 pt-0">{children}</CardContent>
    </Card>
  );
}

// ── Assembly roster ─────────────────────────────────────────────────────────

function AssemblyRosterSection({ rows }: { rows: ReportAssemblyRow[] }) {
  return (
    <Card>
      <CardHeader className="p-4">
        <CardTitle className="text-base">Assembly Roster</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="max-h-[360px]">
          <Table>
            <TableHeader className="sticky top-0 bg-card z-10">
              <TableRow>
                <TableHead>Accession</TableHead>
                <TableHead>Organism</TableHead>
                <TableHead>Phylum</TableHead>
                <TableHead>Biome</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Size (Mb)</TableHead>
                <TableHead className="text-right">BGCs (total)</TableHead>
                <TableHead className="text-right">NRBs (shortlist)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono text-xs">
                    {r.accession}
                    {r.is_type_strain && (
                      <Badge variant="outline" className="ml-1 text-[10px]">
                        type strain
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {r.organism_name ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs">
                    {r.taxonomy_phylum ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs">{r.biome_path || "—"}</TableCell>
                  <TableCell className="text-xs">{r.source_name ?? "—"}</TableCell>
                  <TableCell className="text-right text-xs">
                    {r.assembly_size_mb != null
                      ? r.assembly_size_mb.toFixed(2)
                      : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    {r.total_bgcs_in_assembly}
                  </TableCell>
                  <TableCell className="text-right font-semibold">
                    {r.nrbs_in_shortlist}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

// ── Assembly stats (decorative; reuses backend sunburst/biome/source dicts) ─

function AssemblyStatsSection({
  stats,
}: {
  stats: Record<string, unknown>;
}) {
  // Taxonomy lives in its own NRB-derived TaxonomySunburstSection card; here
  // we only surface biome + per-assembly source distributions.
  const biomeDistribution = useMemo(
    () => (stats?.biome_distribution as CategoryCount[]) ?? [],
    [stats],
  );
  const sourceDistribution = useMemo(
    () => (stats?.source_distribution as CategoryCount[]) ?? [],
    [stats],
  );
  if (!biomeDistribution.length && !sourceDistribution.length) {
    return null;
  }
  return (
    <Card>
      <CardHeader className="p-4">
        <CardTitle className="text-base">Assembly Stats</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
        {biomeDistribution.length > 0 && (
          <PanelCard title="Biome distribution">
            <Plot
              data={[
                {
                  type: "bar",
                  orientation: "h",
                  x: biomeDistribution.map((r) => r.count),
                  y: biomeDistribution.map((r) => r.name),
                  marker: { color: "#f97316" },
                },
              ]}
              layout={{
                autosize: true,
                height: 240,
                margin: { l: 160, r: 16, t: 8, b: 30 },
                xaxis: { title: { text: "Assemblies" } },
                yaxis: { automargin: true, tickfont: { size: 10 } },
              }}
              useResizeHandler
              style={{ width: "100%" }}
              config={{ displayModeBar: false }}
            />
          </PanelCard>
        )}
        {sourceDistribution.length > 0 && (
          <PanelCard title="Source distribution (per assembly)">
            <Plot
              data={[
                {
                  type: "pie",
                  labels: sourceDistribution.map((r) => r.name),
                  values: sourceDistribution.map((r) => r.count),
                  hole: 0.4,
                  textinfo: "label+percent",
                },
              ]}
              layout={{
                autosize: true,
                height: 240,
                margin: { l: 16, r: 16, t: 16, b: 16 },
                showlegend: false,
              }}
              useResizeHandler
              style={{ width: "100%" }}
              config={{ displayModeBar: false }}
            />
          </PanelCard>
        )}
      </CardContent>
    </Card>
  );
}

function fmt(v: number | null): string {
  return v == null ? "—" : v.toFixed(3);
}
