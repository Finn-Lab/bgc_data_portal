import { useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { useTaxonomyTree } from "@/hooks/use-filter-data";
import { useFilterStore } from "@/stores/filter-store";
import { cn } from "@/lib/utils";
import type { TaxonomyNode } from "@/api/types";
import { FilterChip } from "./FilterChip";

function TaxonomyNodeItem({
  node,
  depth,
  selectedRank,
  selectedValue,
  onSelect,
}: {
  node: TaxonomyNode;
  depth: number;
  selectedRank: string;
  selectedValue: string;
  onSelect: (rank: string, value: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isSelected =
    node.rank === selectedRank && node.name === selectedValue;
  const hasChildren = node.children.length > 0;

  return (
    <div>
      <div
        className={cn(
          "flex cursor-pointer items-center gap-1 rounded px-2 py-1 text-sm hover:bg-accent",
          isSelected && "bg-primary/10 font-medium",
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => {
          if (isSelected) {
            onSelect(node.rank, "");
          } else {
            onSelect(node.rank, node.name);
          }
        }}
      >
        {hasChildren && (
          <button
            className="p-0.5"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
          >
            {expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </button>
        )}
        {!hasChildren && <span className="w-4" />}
        <span className="flex-1 truncate">{node.name}</span>
        <Badge variant="secondary" className="text-xs">
          {node.count}
        </Badge>
      </div>
      {expanded &&
        hasChildren &&
        node.children.map((child) => (
          <TaxonomyNodeItem
            key={`${child.rank}-${child.name}`}
            node={child}
            depth={depth + 1}
            selectedRank={selectedRank}
            selectedValue={selectedValue}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

export function TaxonomyFilter() {
  const { data: tree, isLoading } = useTaxonomyTree();
  const [searchText, setSearchText] = useState("");
  const filterStore = useFilterStore();

  const taxonomyPath = filterStore.taxonomyPath;
  const pathParts = taxonomyPath ? taxonomyPath.split(";").filter(Boolean) : [];
  const RANK_ORDER = ["kingdom", "phylum", "class", "order", "family", "genus"];
  const ranks = RANK_ORDER.map((key, i) => ({
    key,
    value: pathParts[i] ?? "",
  }));
  const deepest = [...ranks].reverse().find((r) => r.value);

  function handleSelect(rank: string, value: string) {
    if (!value) {
      const rankIndex = RANK_ORDER.indexOf(rank);
      const newParts = pathParts.slice(0, rankIndex);
      filterStore.setTaxonomyPath(newParts.length > 0 ? newParts.join(";") : "");
    } else {
      const rankIndex = RANK_ORDER.indexOf(rank);
      const newParts = [...pathParts];
      newParts[rankIndex] = value;
      const trimmed = newParts.slice(0, rankIndex + 1);
      filterStore.setTaxonomyPath(trimmed.join(";"));
    }
  }

  function filterTree(nodes: TaxonomyNode[]): TaxonomyNode[] {
    if (!searchText) return nodes;
    const q = searchText.toLowerCase();
    return nodes.reduce<TaxonomyNode[]>((acc, node) => {
      const matchesSelf = node.name.toLowerCase().includes(q);
      const filteredChildren = filterTree(node.children);
      if (matchesSelf || filteredChildren.length > 0) {
        acc.push({
          ...node,
          children: matchesSelf ? node.children : filteredChildren,
        });
      }
      return acc;
    }, []);
  }

  const displayed = filterTree(tree ?? []);
  const label = deepest
    ? `Taxonomy: ${deepest.key} ${deepest.value}`
    : "Taxonomy";

  return (
    <FilterChip
      label={label}
      active={!!deepest}
      onClear={() => filterStore.setTaxonomyPath("")}
      dataTour="taxonomy-filter"
      width="md"
    >
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
        </div>
      ) : (
        <div className="space-y-2">
          <Input
            placeholder="Search taxonomy..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="h-8 text-sm"
          />
          <div className="max-h-64 overflow-auto">
            {displayed.map((node) => (
              <TaxonomyNodeItem
                key={`${node.rank}-${node.name}`}
                node={node}
                depth={0}
                selectedRank={deepest?.key ?? ""}
                selectedValue={deepest?.value ?? ""}
                onSelect={handleSelect}
              />
            ))}
            {displayed.length === 0 && (
              <p className="py-2 text-center text-xs text-muted-foreground">
                No matches
              </p>
            )}
          </div>
        </div>
      )}
    </FilterChip>
  );
}
