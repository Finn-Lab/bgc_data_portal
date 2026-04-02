import { useGenomeRoster } from "@/hooks/use-genome-roster";
import { useSelectionStore } from "@/stores/selection-store";
import { GenomeContextMenu } from "./GenomeContextMenu";
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
  { value: "composite_score", label: "Priority Score" },
  { value: "bgc_count", label: "BGC Count" },
  { value: "bgc_novelty_score", label: "Novelty" },
  { value: "bgc_diversity_score", label: "Diversity" },
  { value: "bgc_density", label: "Density" },
  { value: "organism_name", label: "Organism" },
];

export function GenomeRoster() {
  const {
    data,
    isLoading,
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
  } = useGenomeRoster();

  const activeGenomeId = useSelectionStore((s) => s.activeGenomeId);
  const setActiveGenomeId = useSelectionStore((s) => s.setActiveGenomeId);
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
              <TableHead className="text-xs">Organism</TableHead>
              <TableHead className="text-xs">Family</TableHead>
              <TableHead className="text-xs text-center">BGCs</TableHead>
              <TableHead className="text-xs text-center">Classes</TableHead>
              <TableHead className="text-xs text-right">Score</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((genome) => (
              <GenomeContextMenu
                key={genome.id}
                genomeId={genome.id}
                label={genome.organism_name ?? genome.accession}
              >
                <TableRow
                  className={cn(
                    "cursor-pointer",
                    activeGenomeId === genome.id && "bg-primary/5"
                  )}
                  onClick={() => {
                    setActiveGenomeId(genome.id);
                    setActiveBgcId(null);
                  }}
                >
                  <TableCell className="max-w-[200px] truncate text-xs">
                    <div className="flex items-center gap-1">
                      {genome.is_type_strain && (
                        <Star className="h-3 w-3 flex-shrink-0 fill-amber-400 text-amber-400" />
                      )}
                      <span className="truncate">
                        {genome.organism_name ?? genome.accession}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {genome.taxonomy_family ?? "-"}
                  </TableCell>
                  <TableCell className="text-center text-xs">
                    {genome.bgc_count}
                  </TableCell>
                  <TableCell className="text-center text-xs">
                    {genome.l1_class_count}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <div className="h-2 w-16 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{
                            width: `${Math.round(genome.composite_score * 100)}%`,
                          }}
                        />
                      </div>
                      <span className="font-mono text-xs">
                        {genome.composite_score.toFixed(2)}
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              </GenomeContextMenu>
            ))}
            {items.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="py-8 text-center text-sm text-muted-foreground"
                >
                  No genomes match current filters
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
            {pagination.total_count} genomes
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
