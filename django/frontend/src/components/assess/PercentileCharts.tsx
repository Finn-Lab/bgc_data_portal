import Plot from "react-plotly.js";
import type { PercentileRank, RadarReference } from "@/api/types";

interface PercentileChartsProps {
  percentileRanks: PercentileRank[];
  radarReferences: RadarReference[];
}

export function PercentileCharts({
  percentileRanks,
  radarReferences,
}: PercentileChartsProps) {
  return (
    <div className="grid grid-cols-2 gap-4 xl:grid-cols-3">
      {percentileRanks.map((p) => {
        const ref = radarReferences.find((r) => r.dimension === p.dimension);
        return (
          <div key={p.dimension} className="flex flex-col items-center">
            <span className="mb-1 text-xs font-medium">{p.label}</span>
            <Plot
              data={[
                {
                  type: "indicator",
                  mode: "gauge+number",
                  value: p.percentile_all,
                  gauge: {
                    axis: { range: [0, 100], ticksuffix: "th" },
                    bar: { color: "rgb(59,130,246)" },
                    steps: [
                      { range: [0, 50], color: "rgba(200,200,200,0.2)" },
                      { range: [50, 75], color: "rgba(59,130,246,0.1)" },
                      { range: [75, 100], color: "rgba(59,130,246,0.2)" },
                    ],
                    threshold: {
                      line: { color: "rgb(220,50,50)", width: 2 },
                      thickness: 0.75,
                      value: ref
                        ? (ref.db_p90 / Math.max(p.value, 0.001)) * p.percentile_all
                        : 90,
                    },
                  },
                  number: { suffix: "th" },
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
              Value: {p.value.toFixed(3)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
