import { useAssemblyAggregation } from "@/hooks/use-assembly-aggregation";
import { AssemblyContextMenu } from "@/components/assembly/AssemblyContextMenu";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Star,
} from "lucide-react";

const SORT_OPTIONS = [
  { value: "hit_count", label: "Hit Count" },
  { value: "complete_fraction", label: "Completeness" },
];

export function AssemblyAggregationRoster() {
  const {
    data,
    isLoading,
    hasResults,
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
  } = useAssemblyAggregation();

  if (!hasResults) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Run a query to see assembly aggregation
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

  const items = data?.items ?? [];
  const pagination = data?.pagination;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Select value={sortBy} onValueChange={setSortBy}>
          <SelectTrigger className="h-7 w-36 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value} className="text-xs">
                {o.label}
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
              <TableHead className="text-xs">Organism</TableHead>
              <TableHead className="text-xs">Taxonomy</TableHead>
              <TableHead className="text-xs text-center">Hits</TableHead>
              <TableHead className="text-xs text-right">Complete %</TableHead>
              <TableHead className="w-8" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((assembly) => (
              <AssemblyContextMenu
                key={assembly.assembly_id}
                assemblyId={assembly.assembly_id}
                label={assembly.organism_name ?? assembly.accession}
              >
                <TableRow className="cursor-pointer">
                  <TableCell className="max-w-[180px] truncate text-xs">
                    <div className="flex items-center gap-1">
                      {assembly.is_type_strain && (
                        <Star className="h-3 w-3 flex-shrink-0 fill-amber-400 text-amber-400" />
                      )}
                      {assembly.organism_name ?? assembly.accession}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {assembly.organism_name ?? "-"}
                  </TableCell>
                  <TableCell className="text-center font-mono text-xs">
                    {assembly.hit_count}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {(assembly.complete_fraction * 100).toFixed(0)}%
                  </TableCell>
                </TableRow>
              </AssemblyContextMenu>
            ))}
          </TableBody>
        </Table>
      </div>

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
