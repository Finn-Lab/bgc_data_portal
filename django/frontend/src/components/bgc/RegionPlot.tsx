import { useMemo, useState } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type {
  BgcRegionData,
  RegionCds,
} from "@/api/types";

// ── Constants ────────────────────────────────────────────────────────────────

const SVG_WIDTH = 800;
const CDS_TRACK_Y = 50;
const CDS_HEIGHT = 24;
const CLUSTER_TRACK_Y = 110;
const CLUSTER_HEIGHT = 16;
const CLUSTER_LANE_GAP = 22;
const AXIS_Y = 90;
const SVG_PADDING_X = 10;
const ARROW_PROP = 0.15;
const ARROW_CAP_PX = 12; // max arrow head in SVG units

const DETECTOR_COLORS: Record<string, string> = {
  mibig: "#b3de69",
  sanntis: "#8dd3c7",
  gecco: "#ffffb3",
  antismash: "#bebada",
};
const DEFAULT_CLUSTER_COLOR = "#c8c8c8";

// ── Color generation (port of make_distinct_color_map) ───────────────────────

function hlsToRgb(h: number, l: number, s: number): [number, number, number] {
  if (s === 0) return [l, l, l];
  const hue2rgb = (p: number, q: number, t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return [hue2rgb(p, q, h + 1 / 3), hue2rgb(p, q, h), hue2rgb(p, q, h - 1 / 3)];
}

function makeDistinctColorMap(keys: string[]): Record<string, string> {
  const PHI = 0.618033988749895;
  const SEED = 0.12;
  const L0 = 0.6, L1 = 0.66;
  const S0 = 0.78, S1 = 0.86;
  const unique = [...new Set(keys)].sort();
  const out: Record<string, string> = {};
  for (let i = 0; i < unique.length; i++) {
    const h = (SEED + i * PHI) % 1.0;
    const l = i % 2 === 0 ? L0 : L1;
    const s = Math.floor(i / 2) % 2 === 0 ? S0 : S1;
    const [r, g, b] = hlsToRgb(h, l, s);
    out[unique[i]!] = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
  }
  return out;
}

// ── Lane assignment (port of _assign_nonoverlap_lanes) ───────────────────────

function assignNonoverlapLanes(intervals: [number, number][]): number[] {
  const indexed = intervals.map((iv, i) => ({ i, start: iv[0], end: iv[1] }));
  indexed.sort((a, b) => a.start - b.start);
  const lanesEnd: number[] = [];
  const result: { idx: number; lane: number }[] = [];
  for (const { i, start, end } of indexed) {
    let placed = false;
    for (let ln = 0; ln < lanesEnd.length; ln++) {
      if (start >= lanesEnd[ln]!) {
        lanesEnd[ln] = end;
        result.push({ idx: i, lane: ln });
        placed = true;
        break;
      }
    }
    if (!placed) {
      lanesEnd.push(end);
      result.push({ idx: i, lane: lanesEnd.length - 1 });
    }
  }
  result.sort((a, b) => a.idx - b.idx);
  return result.map((r) => r.lane);
}

// ── Arrow polygon (port of create_trace_data) ────────────────────────────────

function arrowPoints(
  x1: number,
  x2: number,
  strand: number,
  halfHeight: number,
  cy: number,
): string {
  const arrowProp = strand === 0 ? 0 : ARROW_PROP;
  const [start, end] = strand >= 0 ? [x1, x2] : [x2, x1];
  const len = Math.abs(end - start);
  const delta = Math.min(len * arrowProp, ARROW_CAP_PX);
  const headBase =
    strand >= 0 ? Math.max(start, end - delta) : Math.min(start, end + delta);

  const top = cy - halfHeight;
  const bot = cy + halfHeight;
  return [
    `${start},${top}`,
    `${start},${bot}`,
    `${headBase},${bot}`,
    `${end},${cy}`,
    `${headBase},${top}`,
  ].join(" ");
}

// ── Component ────────────────────────────────────────────────────────────────

interface RegionPlotProps {
  data: BgcRegionData;
  onCdsClick: (cds: RegionCds) => void;
  selectedCdsId: string | null;
}

export function RegionPlot({ data, onCdsClick, selectedCdsId }: RegionPlotProps) {
  const [hoveredCdsId, setHoveredCdsId] = useState<string | null>(null);

  const scaleX = (pos: number) =>
    SVG_PADDING_X + (pos / data.region_length) * (SVG_WIDTH - 2 * SVG_PADDING_X);

  // Compute cluster lanes
  const clusterLanes = useMemo(
    () =>
      assignNonoverlapLanes(
        data.cluster_list.map((c) => [c.start, c.end] as [number, number]),
      ),
    [data.cluster_list],
  );
  const maxLane = clusterLanes.length > 0 ? Math.max(...clusterLanes) : 0;

  // GO Slim color map keyed on all GO slim terms in this region
  const goSlimColorMap = useMemo(() => {
    const allSlims = data.domain_list.flatMap((d) => d.go_slim);
    return makeDistinctColorMap(allSlims);
  }, [data.domain_list]);

  // Per-CDS dominant GO slim (most frequent across its domains)
  const cdsGoSlimMap = useMemo(() => {
    const cdsDomainSlims: Record<string, string[]> = {};
    for (const d of data.domain_list) {
      if (d.go_slim.length > 0 && d.parent_cds_id) {
        (cdsDomainSlims[d.parent_cds_id] ??= []).push(...d.go_slim);
      }
    }
    const result: Record<string, string> = {};
    for (const [cdsId, slims] of Object.entries(cdsDomainSlims)) {
      const freq: Record<string, number> = {};
      for (const s of slims) freq[s] = (freq[s] ?? 0) + 1;
      const top = Object.entries(freq).sort((a, b) => b[1] - a[1])[0];
      if (top) result[cdsId] = top[0];
    }
    return result;
  }, [data.domain_list]);

  // Collect unique legend entries
  const legendEntries = useMemo(() => {
    const entries: { label: string; color: string; group: string }[] = [];
    const seen = new Set<string>();

    // Detector colors from clusters
    for (const c of data.cluster_list) {
      const key = c.source.toLowerCase();
      if (!seen.has(key) && key) {
        seen.add(key);
        entries.push({
          label: c.source,
          color: DETECTOR_COLORS[key] || DEFAULT_CLUSTER_COLOR,
          group: "BGC",
        });
      }
    }

    // GO Slim colors from domains
    for (const d of data.domain_list) {
      for (const gs of d.go_slim) {
        if (!seen.has(gs)) {
          seen.add(gs);
          entries.push({
            label: gs,
            color: goSlimColorMap[gs] || "#cfcfcf",
            group: "Pfam GO Slim",
          });
        }
      }
    }
    return entries;
  }, [data.cluster_list, data.domain_list, goSlimColorMap]);

  // Dynamic SVG height based on cluster lane count
  const svgHeight = CLUSTER_TRACK_Y + (maxLane + 1) * CLUSTER_LANE_GAP + 30;

  // X-axis ticks
  const ticks = useMemo(() => {
    const count = 5;
    const step = data.region_length / count;
    return Array.from({ length: count + 1 }, (_, i) => {
      const pos = Math.round(i * step);
      return { pos, label: (data.window_start + pos).toLocaleString() };
    });
  }, [data.region_length, data.window_start]);

  if (data.cds_list.length === 0 && data.cluster_list.length === 0) {
    return (
      <p className="py-4 text-center text-xs text-muted-foreground">
        No CDS found in this region
      </p>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="w-full">
        <svg
          viewBox={`0 0 ${SVG_WIDTH} ${svgHeight}`}
          width="100%"
          preserveAspectRatio="xMidYMid meet"
          className="overflow-visible"
        >
          {/* CDS track background */}
          <rect
            x={SVG_PADDING_X}
            y={CDS_TRACK_Y - CDS_HEIGHT / 2 - 4}
            width={SVG_WIDTH - 2 * SVG_PADDING_X}
            height={CDS_HEIGHT + 8}
            fill="#f8f8f8"
            rx={2}
          />

          {/* Cluster track backgrounds */}
          {Array.from({ length: maxLane + 1 }, (_, ln) => (
            <rect
              key={`cluster-bg-${ln}`}
              x={SVG_PADDING_X}
              y={CLUSTER_TRACK_Y + ln * CLUSTER_LANE_GAP - CLUSTER_HEIGHT / 2 - 2}
              width={SVG_WIDTH - 2 * SVG_PADDING_X}
              height={CLUSTER_HEIGHT + 4}
              fill="#fdf6e3"
              rx={2}
            />
          ))}

          {/* Cluster rectangles */}
          {data.cluster_list.map((cluster, i) => {
            const lane = clusterLanes[i]!;
            const cx1 = scaleX(cluster.start);
            const cx2 = scaleX(cluster.end);
            const cy = CLUSTER_TRACK_Y + lane * CLUSTER_LANE_GAP;
            const color =
              DETECTOR_COLORS[cluster.source.toLowerCase()] ||
              DEFAULT_CLUSTER_COLOR;
            return (
              <Tooltip key={`cluster-${i}`}>
                <TooltipTrigger asChild>
                  <rect
                    x={cx1}
                    y={cy - CLUSTER_HEIGHT / 2}
                    width={cx2 - cx1}
                    height={CLUSTER_HEIGHT}
                    fill={color}
                    rx={2}
                    opacity={0.8}
                  />
                </TooltipTrigger>
                <TooltipContent>
                  <div className="text-xs">
                    <p className="font-medium">{cluster.accession}</p>
                    <p>Source: {cluster.source || "Unknown"}</p>
                    {cluster.bgc_classes.length > 0 && (
                      <p>Classes: {cluster.bgc_classes.join(", ")}</p>
                    )}
                  </div>
                </TooltipContent>
              </Tooltip>
            );
          })}

          {/* CDS arrows — colored by dominant GO slim term */}
          {data.cds_list.map((cds) => {
            const cx1 = scaleX(cds.start);
            const cx2 = scaleX(cds.end);
            const isSelected = selectedCdsId === cds.protein_id;
            const isHovered = hoveredCdsId === cds.protein_id;
            const dominantSlim = cdsGoSlimMap[cds.protein_id];
            const fill = dominantSlim ? (goSlimColorMap[dominantSlim] ?? "#e8e8e8") : "#e8e8e8";
            return (
              <Tooltip key={`cds-${cds.protein_id}`}>
                <TooltipTrigger asChild>
                  <polygon
                    points={arrowPoints(
                      cx1,
                      cx2,
                      cds.strand,
                      CDS_HEIGHT / 2,
                      CDS_TRACK_Y,
                    )}
                    fill={fill}
                    stroke="black"
                    strokeWidth={isSelected ? 2.5 : isHovered ? 1.8 : 1.2}
                    cursor="pointer"
                    onClick={() => onCdsClick(cds)}
                    onMouseEnter={() => setHoveredCdsId(cds.protein_id)}
                    onMouseLeave={() => setHoveredCdsId(null)}
                  />
                </TooltipTrigger>
                <TooltipContent>
                  <div className="text-xs space-y-0.5">
                    <p className="font-medium">{cds.protein_id}</p>
                    <p>
                      {data.window_start + cds.start}..{data.window_start + cds.end}{" "}
                      ({cds.strand >= 0 ? "+" : "-"})
                    </p>
                    <p>{cds.protein_length} aa</p>
                    {dominantSlim && (
                      <p className="text-muted-foreground">{dominantSlim}</p>
                    )}
                    {cds.pfam.length > 0 && (
                      <div className="mt-1 border-t pt-1 space-y-0.5">
                        {[...new Map(cds.pfam.map((pf) => [pf.accession, pf])).values()].map((pf) => (
                          <p key={pf.accession}>
                            <span className="font-medium">{pf.accession}</span>
                            {pf.description && ` — ${pf.description}`}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                </TooltipContent>
              </Tooltip>
            );
          })}


          {/* X-axis */}
          <line
            x1={SVG_PADDING_X}
            y1={AXIS_Y}
            x2={SVG_WIDTH - SVG_PADDING_X}
            y2={AXIS_Y}
            stroke="#999"
            strokeWidth={0.5}
          />
          {ticks.map((tick) => {
            const tx = scaleX(tick.pos);
            return (
              <g key={`tick-${tick.pos}`}>
                <line x1={tx} y1={AXIS_Y} x2={tx} y2={AXIS_Y + 4} stroke="#999" strokeWidth={0.5} />
                <text
                  x={tx}
                  y={AXIS_Y + 13}
                  textAnchor="middle"
                  fontSize={8}
                  fill="#666"
                >
                  {tick.label}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Legend */}
        {legendEntries.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
            {legendEntries.map((entry) => (
              <span key={entry.label} className="flex items-center gap-1">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-sm border border-black/20"
                  style={{ backgroundColor: entry.color }}
                />
                {entry.label}
              </span>
            ))}
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}
