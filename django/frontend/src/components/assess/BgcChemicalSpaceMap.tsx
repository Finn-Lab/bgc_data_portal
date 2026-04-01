import { useState } from "react";
import Plot from "react-plotly.js";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type {
  AssessChemicalSpacePoint,
  AssessNearestNeighborPoint,
  MibigReferencePoint,
} from "@/api/types";

// Match BgcScatter.tsx color scheme exactly
const BGC_CLASS_COLORS: Record<string, string> = {
  Polyketide: "#3b82f6",
  NRP: "#ef4444",
  RiPP: "#22c55e",
  Terpene: "#f97316",
  Saccharide: "#a855f7",
  Alkaloid: "#14b8a6",
  Other: "#6b7280",
};

interface BgcChemicalSpaceMapProps {
  submittedPoint: AssessChemicalSpacePoint | null;
  neighbors: AssessNearestNeighborPoint[];
  mibigPoints: MibigReferencePoint[];
}

export function BgcChemicalSpaceMap({
  submittedPoint,
  neighbors,
  mibigPoints,
}: BgcChemicalSpaceMapProps) {
  const [showMibig, setShowMibig] = useState(true);
  const traces: Plotly.Data[] = [];

  // MIBiG background — grey triangles matching BgcScatter
  if (showMibig && mibigPoints.length > 0) {
    traces.push({
      type: "scatter",
      mode: "markers",
      x: mibigPoints.map((p) => p.umap_x),
      y: mibigPoints.map((p) => p.umap_y),
      marker: { symbol: "triangle-up", size: 5, color: "#d1d5db", opacity: 0.7 },
      text: mibigPoints.map((p) => `${p.accession} (${p.compound_name})`),
      hoverinfo: "text",
      name: "MIBiG references",
    });
  }

  // DB nearest neighbors — colored by BGC class
  const dbNeighbors = neighbors.filter((n) => !n.is_mibig);
  if (dbNeighbors.length > 0) {
    traces.push({
      type: "scatter",
      mode: "markers",
      x: dbNeighbors.map((n) => n.umap_x),
      y: dbNeighbors.map((n) => n.umap_y),
      marker: {
        size: 7,
        color: dbNeighbors.map(() => "#94a3b8"),
        opacity: 0.6,
      },
      text: dbNeighbors.map(
        (n) => `${n.label}<br>Distance: ${n.distance.toFixed(4)}`
      ),
      hoverinfo: "text",
      name: "Nearest DB BGCs",
    });
  }

  // MIBiG nearest neighbors (labeled, orange triangles)
  const mibigNeighbors = neighbors.filter((n) => n.is_mibig);
  if (mibigNeighbors.length > 0) {
    traces.push({
      type: "scatter",
      mode: "markers+text",
      x: mibigNeighbors.map((n) => n.umap_x),
      y: mibigNeighbors.map((n) => n.umap_y),
      marker: { symbol: "triangle-up", size: 10, color: "#f97316" },
      text: mibigNeighbors.map((n) => n.label),
      textposition: "top center",
      textfont: { size: 8 },
      hovertext: mibigNeighbors.map(
        (n) => `${n.label}<br>Distance: ${n.distance.toFixed(4)}`
      ),
      hoverinfo: "text",
      name: "Nearest MIBiG",
    });
  }

  // Submitted BGC as blue star
  if (submittedPoint) {
    traces.push({
      type: "scatter",
      mode: "markers",
      x: [submittedPoint.umap_x],
      y: [submittedPoint.umap_y],
      marker: {
        symbol: "star",
        size: 18,
        color: "#3b82f6",
        line: { color: "black", width: 1.5 },
      },
      text: [`Submitted: ${submittedPoint.accession}`],
      hoverinfo: "text",
      name: "Submitted BGC",
    });
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <Checkbox
          id="show-mibig-assess"
          checked={showMibig}
          onCheckedChange={(v) => setShowMibig(v === true)}
        />
        <Label htmlFor="show-mibig-assess" className="text-xs">
          Show MIBiG references
        </Label>
      </div>
      <Plot
        data={traces}
        layout={{
          xaxis: { title: "UMAP 1", zeroline: false },
          yaxis: { title: "UMAP 2", zeroline: false },
          showlegend: true,
          legend: { orientation: "h", y: -0.15 },
          margin: { t: 10, b: 60, l: 60, r: 20 },
          autosize: true,
        }}
        config={{ responsive: true, displayModeBar: false }}
        useResizeHandler
        style={{ width: "100%", height: 400 }}
      />
    </div>
  );
}
