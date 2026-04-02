import type { PercentileRank } from "@/api/types";

interface GenomeRankCardProps {
  dbRank: number;
  dbTotal: number;
  compositeScore: number;
  percentileRanks: PercentileRank[];
}

export function GenomeRankCard({
  dbRank,
  dbTotal,
  compositeScore,
  percentileRanks,
}: GenomeRankCardProps) {
  return (
    <div className="space-y-4">
      {/* Hero rank */}
      <div className="flex items-baseline gap-3">
        <span className="text-4xl font-bold text-primary">#{dbRank}</span>
        <span className="text-sm text-muted-foreground">
          of {dbTotal.toLocaleString()} genomes by priority score
        </span>
      </div>
      <div className="text-sm">
        Composite score:{" "}
        <span className="font-semibold">{(compositeScore * 100).toFixed(1)}%</span>
      </div>

      {/* Percentile table */}
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-1.5">Dimension</th>
            <th className="py-1.5 text-right">Value</th>
            <th className="py-1.5 text-right">vs All</th>
            <th className="py-1.5 text-right">vs Type Strains</th>
          </tr>
        </thead>
        <tbody>
          {percentileRanks.map((p) => (
            <tr key={p.dimension} className="border-b last:border-0">
              <td className="py-1.5">{p.label}</td>
              <td className="py-1.5 text-right font-mono text-xs">
                {p.value.toFixed(3)}
              </td>
              <td className="py-1.5 text-right">
                <PercentileBadge value={p.percentile_all} />
              </td>
              <td className="py-1.5 text-right">
                <PercentileBadge value={p.percentile_type_strain} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PercentileBadge({ value }: { value: number }) {
  const color =
    value >= 90
      ? "bg-green-100 text-green-800"
      : value >= 75
        ? "bg-blue-100 text-blue-800"
        : value >= 50
          ? "bg-yellow-100 text-yellow-800"
          : "bg-gray-100 text-gray-600";

  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${color}`}
    >
      {value.toFixed(0)}th
    </span>
  );
}
