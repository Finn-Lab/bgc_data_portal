import Plot from "react-plotly.js";
import type { BgcNoveltyItem } from "@/api/types";

const BGC_CLASS_COLORS: Record<string, string> = {
  Polyketide: "#3b82f6",
  NRP: "#ef4444",
  RiPP: "#22c55e",
  Terpene: "#f97316",
  Saccharide: "#a855f7",
  Alkaloid: "#ec4899",
  Other: "#6b7280",
};

interface BgcNoveltyStripProps {
  bgcNovelty: BgcNoveltyItem[];
}

export function BgcNoveltyStrip({ bgcNovelty }: BgcNoveltyStripProps) {
  if (bgcNovelty.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No BGCs found.</p>;
  }

  const sorted = [...bgcNovelty].sort((a, b) => b.novelty_vs_db - a.novelty_vs_db);

  return (
    <Plot
      data={[
        {
          type: "bar",
          orientation: "h",
          y: sorted.map((b) => b.accession),
          x: sorted.map((b) => b.novelty_vs_db),
          marker: {
            color: sorted.map(
              (b) => BGC_CLASS_COLORS[b.classification_path?.split('.')[0]] || BGC_CLASS_COLORS.Other
            ),
          },
          text: sorted.map(
            (b) =>
              `${b.classification_path}<br>vs DB: ${b.novelty_vs_db.toFixed(3)}<br>vs Validated: ${b.novelty_vs_validated.toFixed(3)}`
          ),
          hoverinfo: "text",
        },
      ]}
      layout={{
        xaxis: { title: "Novelty Score (vs DB)", range: [0, 1] },
        yaxis: {
          automargin: true,
          categoryorder: "array",
          categoryarray: sorted.map((b) => b.accession).reverse(),
        },
        margin: { t: 10, b: 40, l: 120, r: 20 },
        autosize: true,
        height: Math.max(250, sorted.length * 28),
      }}
      config={{ responsive: true, displayModeBar: false }}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
    />
  );
}
