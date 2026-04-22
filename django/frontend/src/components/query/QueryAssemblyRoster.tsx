import { useQueryAssemblyRoster } from "@/hooks/use-query-assembly-roster";
import { useParentAssemblies } from "@/hooks/use-parent-assemblies";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { AssemblyContextMenu } from "@/components/assembly/AssemblyContextMenu";
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

export function QueryAssemblyRoster() {
  const bgcShortlist = useShortlistStore((s) => s.bgcs);
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const activeAssemblyId = useSelectionStore((s) => s.activeAssemblyId);
  const setActiveAssemblyId = useSelectionStore((s) => s.setActiveAssemblyId);

  // Resolve BGC IDs -> parent assembly IDs
  const bgcIds =
    bgcShortlist.length > 0
      ? bgcShortlist.map((b) => b.id)
      : activeBgcId
        ? [activeBgcId]
        : [];

  const { data: assemblyIds } = useParentAssemblies(bgcIds);

  const {
    data,
    isLoading,
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
  } = useQueryAssemblyRoster(assemblyIds ?? []);

  const items = data?.items ?? [];
  const pagination = data?.pagination;

  if (!assemblyIds && bgcIds.length > 0) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    );
  }

  if (bgcIds.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Add BGCs to shortlist to view their parent assemblies
      </p>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    );
  }

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
                </TableRow>
              </AssemblyContextMenu>
            ))}
            {items.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="py-8 text-center text-sm text-muted-foreground"
                >
                  No assemblies found
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
