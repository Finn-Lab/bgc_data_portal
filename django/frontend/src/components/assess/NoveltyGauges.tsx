import Plot from "react-plotly.js";
import type { NoveltyDecomposition } from "@/api/types";

interface NoveltyGaugesProps {
  novelty: NoveltyDecomposition;
}

const GAUGE_CONFIG = [
  { key: "sequence_novelty" as const, label: "Sequence", color: "rgb(59,130,246)" },
  { key: "chemistry_novelty" as const, label: "Chemistry", color: "rgb(96,165,250)" },
  { key: "architecture_novelty" as const, label: "Architecture", color: "rgb(37,99,235)" },
];

export function NoveltyGauges({ novelty }: NoveltyGaugesProps) {
  return (
    <div className="grid grid-cols-3 gap-4">
      {GAUGE_CONFIG.map(({ key, label, color }) => (
        <div key={key} className="flex flex-col items-center">
          <span className="mb-1 text-xs font-medium">{label} Novelty</span>
          <Plot
            data={[
              {
                type: "indicator",
                mode: "gauge+number",
                value: novelty[key],
                gauge: {
                  axis: { range: [0, 1], tickvals: [0, 0.25, 0.5, 0.75, 1] },
                  bar: { color },
                  steps: [
                    { range: [0, 0.33], color: "rgba(200,200,200,0.2)" },
                    { range: [0.33, 0.66], color: "rgba(59,130,246,0.1)" },
                    { range: [0.66, 1], color: "rgba(59,130,246,0.2)" },
                  ],
                },
                number: { valueformat: ".3f" },
              },
            ]}
            layout={{
              height: 180,
              margin: { t: 20, b: 10, l: 20, r: 20 },
              autosize: true,
            }}
            config={{ responsive: true, displayModeBar: false }}
            useResizeHandler
            style={{ width: "100%", height: 180 }}
          />
          <span className="text-[10px] text-muted-foreground">
            Score: {novelty[key].toFixed(3)}
          </span>
        </div>
      ))}
    </div>
  );
}
