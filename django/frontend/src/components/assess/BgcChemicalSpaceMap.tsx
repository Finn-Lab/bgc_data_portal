import { useState } from "react";
import Plot from "react-plotly.js";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type {
  AssessChemicalSpacePoint,
  AssessNearestNeighborPoint,
  ValidatedReferencePoint,
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
  validatedPoints: ValidatedReferencePoint[];
}

export function BgcChemicalSpaceMap({
  submittedPoint,
  neighbors,
  validatedPoints,
}: BgcChemicalSpaceMapProps) {
  const [showValidated, setShowValidated] = useState(true);
  const traces: Plotly.Data[] = [];

  // Validated background — grey triangles matching BgcScatter
  if (showValidated && validatedPoints.length > 0) {
    traces.push({
      type: "scatter",
      mode: "markers",
      x: validatedPoints.map((p) => p.umap_x),
      y: validatedPoints.map((p) => p.umap_y),
      marker: { symbol: "triangle-up", size: 5, color: "#d1d5db", opacity: 0.7 },
      text: validatedPoints.map((p) => `${p.accession} (${p.compound_name})`),
      hoverinfo: "text",
      name: "Validated references",
    });
  }

  // DB nearest neighbors — colored by BGC class
  const dbNeighbors = neighbors.filter((n) => !n.is_validated);
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

  // Validated nearest neighbors (labeled, orange triangles)
  const validatedNeighbors = neighbors.filter((n) => n.is_validated);
  if (validatedNeighbors.length > 0) {
    traces.push({
      type: "scatter",
      mode: "markers+text",
      x: validatedNeighbors.map((n) => n.umap_x),
      y: validatedNeighbors.map((n) => n.umap_y),
      marker: { symbol: "triangle-up", size: 10, color: "#f97316" },
      text: validatedNeighbors.map((n) => n.label),
      textposition: "top center",
      textfont: { size: 8 },
      hovertext: validatedNeighbors.map(
        (n) => `${n.label}<br>Distance: ${n.distance.toFixed(4)}`
      ),
      hoverinfo: "text",
      name: "Nearest Validated",
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
          id="show-validated-assess"
          checked={showValidated}
          onCheckedChange={(v) => setShowValidated(v === true)}
        />
        <Label htmlFor="show-validated-assess" className="text-xs">
          Show validated references
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
