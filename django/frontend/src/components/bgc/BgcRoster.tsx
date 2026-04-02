import { useBgcRoster } from "@/hooks/use-bgc-roster";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { BgcContextMenu } from "./BgcContextMenu";
import { Badge } from "@/components/ui/badge";
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
import { ArrowUpDown, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const SORT_OPTIONS = [
  { value: "novelty_score", label: "Novelty" },
  { value: "size_kb", label: "Size (kb)" },
  { value: "domain_novelty", label: "Domain Novelty" },
  { value: "classification_l1", label: "BGC Class" },
  { value: "accession", label: "Accession" },
];

interface BgcRosterProps {
  assemblyIdOverride?: number;
}

export function BgcRoster({ assemblyIdOverride }: BgcRosterProps = {}) {
  const {
    data,
    isLoading,
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
  } = useBgcRoster(assemblyIdOverride);

  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const setActiveBgcId = useSelectionStore((s) => s.setActiveBgcId);
  const assemblyShortlist = useShortlistStore((s) => s.assemblies);
  const showAssemblyBadge = assemblyShortlist.length > 1;

  const items = data?.items ?? [];
  const pagination = data?.pagination;

  if (!data && !isLoading) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Add assemblies to shortlist to view their BGCs
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
    <div className="flex flex-col h-full gap-2">
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

      <div className="overflow-auto flex-1 min-h-0">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-background">
            <TableRow>
              <TableHead className="text-xs">Accession</TableHead>
              <TableHead className="text-xs">Class</TableHead>
              <TableHead className="text-xs text-right">Size (kb)</TableHead>
              <TableHead className="text-xs text-right">Novelty</TableHead>
              <TableHead className="text-xs text-right">Dom. Nov.</TableHead>
              <TableHead className="text-xs text-center">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((bgc) => (
              <BgcContextMenu
                key={bgc.id}
                bgcId={bgc.id}
                label={bgc.accession}
              >
                <TableRow
                  className={cn(
                    "cursor-pointer",
                    activeBgcId === bgc.id && "bg-primary/5"
                  )}
                  onClick={() => setActiveBgcId(bgc.id)}
                >
                  <TableCell className="font-mono text-xs">
                    <div className="flex items-center gap-1">
                      {bgc.accession}
                      {showAssemblyBadge && bgc.assembly_accession && (
                        <Badge variant="outline" className="text-[9px] px-1 py-0">
                          {bgc.assembly_accession}
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">
                    {bgc.classification_l1}
                    {bgc.classification_l2 && (
                      <span className="text-muted-foreground">
                        {" / "}
                        {bgc.classification_l2}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {bgc.size_kb.toFixed(1)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {bgc.novelty_score.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {bgc.domain_novelty.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-center">
                    {bgc.is_partial ? (
                      <Badge variant="outline" className="text-[10px]">
                        partial
                      </Badge>
                    ) : (
                      <Badge
                        variant="secondary"
                        className="text-[10px] bg-green-100 text-green-700"
                      >
                        complete
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              </BgcContextMenu>
            ))}
            {items.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-8 text-center text-sm text-muted-foreground"
                >
                  No BGCs found
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
            {pagination.total_count} BGCs
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
