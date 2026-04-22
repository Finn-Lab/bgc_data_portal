import { useAssemblyRoster } from "@/hooks/use-assembly-roster";
import { useSelectionStore } from "@/stores/selection-store";
import { AssemblyContextMenu } from "./AssemblyContextMenu";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Star, ArrowUpDown, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const SORT_OPTIONS = [
  { value: "bgc_novelty_score", label: "Novelty" },
  { value: "bgc_count", label: "BGC Count" },
  { value: "bgc_diversity_score", label: "Diversity" },
  { value: "bgc_density", label: "Density" },
  { value: "organism_name", label: "Organism" },
];

export function AssemblyRoster() {
  const {
    data,
    isLoading,
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
  } = useAssemblyRoster();

  const activeAssemblyId = useSelectionStore((s) => s.activeAssemblyId);
  const setActiveAssemblyId = useSelectionStore((s) => s.setActiveAssemblyId);
  const setActiveBgcId = useSelectionStore((s) => s.setActiveBgcId);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  const items = data?.items ?? [];
  const pagination = data?.pagination;

  return (
    <div className="space-y-2">
      {/* Sort controls */}
      <div className="flex items-center gap-2">
        <Select value={sortBy} onValueChange={setSortBy}>
          <SelectTrigger className="h-7 w-40 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value} className="text-xs">
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0"
          onClick={() => setOrder(order === "asc" ? "desc" : "asc")}
        >
          <ArrowUpDown className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Ref. DB</TableHead>
              <TableHead className="text-xs">Taxonomy</TableHead>
              <TableHead className="text-xs text-center">BGCs</TableHead>
              <TableHead className="text-xs text-center">Classes</TableHead>
              <TableHead className="text-xs text-right">Novelty</TableHead>
              <TableHead className="text-xs text-right">Diversity</TableHead>
              <TableHead className="text-xs text-right">Density</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((assembly) => (
              <AssemblyContextMenu
                key={assembly.id}
                assemblyId={assembly.id}
                label={assembly.organism_name ?? assembly.accession}
              >
                <TableRow
                  className={cn(
                    "cursor-pointer",
                    activeAssemblyId === assembly.id && "bg-primary/5"
                  )}
                  onClick={() => {
                    setActiveAssemblyId(assembly.id);
                    setActiveBgcId(null);
                  }}
                >
                  <TableCell className="max-w-[200px] truncate text-xs">
                    <div className="flex items-center gap-1">
                      {assembly.is_type_strain && (
                        <Star className="h-3 w-3 flex-shrink-0 fill-amber-400 text-amber-400" />
                      )}
                      <span className="truncate">
                        {assembly.source_name ?? "-"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {assembly.organism_name ?? "-"}
                  </TableCell>
                  <TableCell className="text-center text-xs">
                    {assembly.bgc_count}
                  </TableCell>
                  <TableCell className="text-center text-xs">
                    {assembly.l1_class_count}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {assembly.bgc_novelty_score.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {assembly.bgc_diversity_score.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {assembly.bgc_density.toFixed(2)}
                  </TableCell>
                </TableRow>
              </AssemblyContextMenu>
            ))}
            {items.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="py-8 text-center text-sm text-muted-foreground"
                >
                  No assemblies match current filters
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {pagination && pagination.total_pages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <span className="text-xs text-muted-foreground">
            {pagination.total_count} assemblies
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <span className="px-2 text-xs">
              {page} / {pagination.total_pages}
            </span>
            <Button
              variant="outline"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={page >= pagination.total_pages}
              onClick={() => setPage(page + 1)}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
