import { useEffect, useState } from "react";
import { useFilterStore } from "@/stores/filter-store";
import { FilterChip } from "./FilterChip";
import { Input } from "@/components/ui/input";

function parseBound(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0) return null;
  return n;
}

function summary(min: number | null, max: number | null): string {
  if (min == null && max == null) return "Length";
  if (min != null && max != null) return `Length: ${min}–${max} kb`;
  if (min != null) return `Length: ≥${min} kb`;
  return `Length: ≤${max} kb`;
}

export function LengthFilter() {
  const minLengthKb = useFilterStore((s) => s.minLengthKb);
  const maxLengthKb = useFilterStore((s) => s.maxLengthKb);
  const setLengthRangeKb = useFilterStore((s) => s.setLengthRangeKb);

  // Local draft strings so the user can type freely; the store is updated
  // on blur / Enter (and on Clear). Re-seeded when the store changes from
  // outside (e.g. clearFilters).
  const [minDraft, setMinDraft] = useState<string>(
    minLengthKb == null ? "" : String(minLengthKb),
  );
  const [maxDraft, setMaxDraft] = useState<string>(
    maxLengthKb == null ? "" : String(maxLengthKb),
  );
  useEffect(() => {
    setMinDraft(minLengthKb == null ? "" : String(minLengthKb));
  }, [minLengthKb]);
  useEffect(() => {
    setMaxDraft(maxLengthKb == null ? "" : String(maxLengthKb));
  }, [maxLengthKb]);

  const commit = () => {
    let min = parseBound(minDraft);
    let max = parseBound(maxDraft);
    // Swap if the user inverted the bounds; saves them a second edit.
    if (min != null && max != null && min > max) {
      [min, max] = [max, min];
    }
    setLengthRangeKb(min, max);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.currentTarget.blur();
    }
  };

  const isActive = minLengthKb != null || maxLengthKb != null;

  return (
    <FilterChip
      label={summary(minLengthKb, maxLengthKb)}
      active={isActive}
      onClear={() => setLengthRangeKb(null, null)}
      dataTour="length-filter"
      width="sm"
    >
      <div className="flex flex-col gap-2">
        <div className="text-xs text-muted-foreground">
          iBGC length range (kb). Leave a side blank for no bound.
        </div>
        <div className="flex items-center gap-2">
          <label className="flex-1 text-xs">
            <span className="mb-1 block text-muted-foreground">Min</span>
            <Input
              type="number"
              min={0}
              step="any"
              inputMode="decimal"
              value={minDraft}
              onChange={(e) => setMinDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={onKeyDown}
              placeholder="—"
            />
          </label>
          <label className="flex-1 text-xs">
            <span className="mb-1 block text-muted-foreground">Max</span>
            <Input
              type="number"
              min={0}
              step="any"
              inputMode="decimal"
              value={maxDraft}
              onChange={(e) => setMaxDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={onKeyDown}
              placeholder="—"
            />
          </label>
        </div>
      </div>
    </FilterChip>
  );
}
