import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useFilterStore } from "@/stores/filter-store";
import { FilterChip } from "./FilterChip";

export function AccessionsFilter() {
  const bgcAccession = useFilterStore((s) => s.bgcAccession);
  const setBgcAccession = useFilterStore((s) => s.setBgcAccession);
  const assemblyAccession = useFilterStore((s) => s.assemblyAccession);
  const setAssemblyAccession = useFilterStore((s) => s.setAssemblyAccession);

  const activeCount = (bgcAccession ? 1 : 0) + (assemblyAccession ? 1 : 0);

  return (
    <FilterChip
      label="Accessions"
      count={activeCount}
      onClear={() => {
        setBgcAccession("");
        setAssemblyAccession("");
      }}
      width="md"
    >
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label className="text-xs">Assembly accession</Label>
          <Input
            placeholder="e.g. ERZ..."
            value={assemblyAccession}
            onChange={(e) => setAssemblyAccession(e.target.value)}
            className="vf-form__input h-8 text-xs"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">BGC accession (MGYB)</Label>
          <Input
            placeholder="e.g. MGYB000000000001"
            value={bgcAccession}
            onChange={(e) => setBgcAccession(e.target.value)}
            className="vf-form__input h-8 text-xs"
          />
        </div>
      </div>
    </FilterChip>
  );
}
