import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useFilterStore } from "@/stores/filter-store";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { FilterChip } from "./FilterChip";

export function BiomeLineageFilter() {
  const biomeLineage = useFilterStore((s) => s.biomeLineage);
  const setBiomeLineage = useFilterStore((s) => s.setBiomeLineage);
  const isActive = !!biomeLineage;

  return (
    <FilterChip
      label={isActive ? `Biome: ${biomeLineage}` : "Biome lineage"}
      active={isActive}
      onClear={() => setBiomeLineage("")}
      dataTour="biome-lineage"
      width="md"
    >
      <div className="space-y-1.5">
        <Label className="flex items-center gap-1 text-xs">
          Biome lineage <HelpTooltip tooltipKey="biome_lineage" side="right" />
        </Label>
        <Input
          autoFocus
          placeholder="e.g. root:Environmental:Soil"
          value={biomeLineage}
          onChange={(e) => setBiomeLineage(e.target.value)}
          className="vf-form__input h-8 text-xs"
        />
      </div>
    </FilterChip>
  );
}
