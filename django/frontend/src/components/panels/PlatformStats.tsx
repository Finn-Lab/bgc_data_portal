import { useDiscoveryStats } from "@/hooks/use-discovery-stats";

const NUMBER_FMT = new Intl.NumberFormat("en-US");

interface StatTileProps {
  value: number | undefined;
  label: string;
  isLoading: boolean;
}

function StatTile({ value, label, isLoading }: StatTileProps) {
  return (
    <div className="flex flex-col items-center justify-center px-3 leading-tight">
      <div className="text-lg font-bold tabular-nums">
        {isLoading || value === undefined ? "—" : NUMBER_FMT.format(value)}
      </div>
      <div className="text-[0.65rem] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
    </div>
  );
}

export function PlatformStats() {
  const { data, isLoading } = useDiscoveryStats();

  return (
    <div
      className="ml-auto hidden items-stretch divide-x divide-border md:flex"
      aria-label="Discovery Platform totals"
    >
      <StatTile
        value={data?.validated_bgcs}
        label="Validated BGCs"
        isLoading={isLoading}
      />
      <StatTile
        value={data?.ibgcs}
        label="Integrated BGCs"
        isLoading={isLoading}
      />
      <StatTile
        value={data?.total_bgc_predictions}
        label="Predicted BGCs"
        isLoading={isLoading}
      />
      <StatTile value={data?.genomes} label="Genomes" isLoading={isLoading} />
      <StatTile
        value={data?.metagenomes}
        label="Metagenomes"
        isLoading={isLoading}
      />
    </div>
  );
}
