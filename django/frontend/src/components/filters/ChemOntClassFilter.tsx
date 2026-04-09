import { useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useChemOntClasses } from "@/hooks/use-filter-data";
import { useFilterStore } from "@/stores/filter-store";
import type { ChemOntClassNode } from "@/api/types";

function ChemOntNode({
  node,
  depth,
  selected,
  onToggle,
}: {
  node: ChemOntClassNode;
  depth: number;
  selected: string[];
  onToggle: (chemontId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasChildren = node.children.length > 0;
  const isChecked = selected.includes(node.chemont_id);

  return (
    <div className="min-w-0">
      <div
        className="flex items-center gap-1 py-0.5 min-w-0"
        style={{ paddingLeft: `${depth * 10 + 4}px` }}
      >
        {hasChildren ? (
          <button
            className="p-0.5 shrink-0"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </button>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <Checkbox
          id={`chemont-${node.chemont_id}`}
          checked={isChecked}
          onCheckedChange={() => onToggle(node.chemont_id)}
          className="h-3.5 w-3.5 shrink-0"
        />
        <label
          htmlFor={`chemont-${node.chemont_id}`}
          className="min-w-0 flex-1 cursor-pointer truncate text-xs"
          title={`${node.name} (${node.chemont_id})`}
        >
          {node.name}
        </label>
        <Badge variant="secondary" className="shrink-0 text-[10px] px-1">
          {node.count}
        </Badge>
      </div>
      {expanded &&
        node.children.map((child) => (
          <ChemOntNode
            key={child.chemont_id}
            node={child}
            depth={depth + 1}
            selected={selected}
            onToggle={onToggle}
          />
        ))}
    </div>
  );
}

export function ChemOntClassFilter() {
  const { data: chemontClasses, isLoading } = useChemOntClasses();
  const chemontIds = useFilterStore((s) => s.chemontIds);
  const setChemontIds = useFilterStore((s) => s.setChemontIds);

  function handleToggle(chemontId: string) {
    const next = chemontIds.includes(chemontId)
      ? chemontIds.filter((id) => id !== chemontId)
      : [...chemontIds, chemontId];
    setChemontIds(next);
  }

  if (isLoading) {
    return <Skeleton className="h-20 w-full" />;
  }

  return (
    <div className="space-y-2 min-w-0">
      <span className="text-sm font-medium">ChemOnt Chemical Class</span>
      <div className="max-h-48 overflow-auto min-w-0">
        {(chemontClasses ?? []).map((node) => (
          <ChemOntNode
            key={node.chemont_id}
            node={node}
            depth={0}
            selected={chemontIds}
            onToggle={handleToggle}
          />
        ))}
      </div>
    </div>
  );
}
