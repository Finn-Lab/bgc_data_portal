import { useDomainQuery } from "@/hooks/use-domain-query";
import { useSimilarBgcQuery } from "@/hooks/use-similar-bgc-query";
import { useChemicalQuery } from "@/hooks/use-chemical-query";
import { useQueryStore } from "@/stores/query-store";
import { useSelectionStore } from "@/stores/selection-store";
import { BgcContextMenu } from "@/components/bgc/BgcContextMenu";
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
import { ArrowUpDown, ChevronLeft, ChevronRight, Star } from "lucide-react";
import { cn } from "@/lib/utils";

const SORT_OPTIONS = [
  { value: "similarity_score", label: "Query Similarity" },
  { value: "novelty_score", label: "Novelty" },
  { value: "domain_novelty", label: "Domain Novelty" },
  { value: "size_kb", label: "Size" },
  { value: "classification_path", label: "Class" },
  { value: "accession", label: "Accession" },
];

export function QueryResultsRoster() {
  const similarBgcSourceId = useQueryStore((s) => s.similarBgcSourceId);
  const smilesQuery = useQueryStore((s) => s.smilesQuery);
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const setActiveBgcId = useSelectionStore((s) => s.setActiveBgcId);

  const domainQuery = useDomainQuery();
  const similarQuery = useSimilarBgcQuery();
  const chemicalQuery = useChemicalQuery();

  // Pick the active query: similar BGC > chemical > domain
  const query = similarBgcSourceId
    ? similarQuery
    : smilesQuery.trim()
      ? chemicalQuery
      : domainQuery;
  const { data, isLoading, page, setPage, sortBy, setSortBy, order, setOrder } = query;

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    );
  }

  const items = data?.items ?? [];
  const pagination = data?.pagination;

  if (items.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {similarBgcSourceId
          ? "No similar BGCs found"
          : "Run a query to see results"}
      </p>
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
              <TableHead className="text-xs">Accession</TableHead>
              <TableHead className="text-xs">Class</TableHead>
              <TableHead className="text-xs">Ref. DB</TableHead>
              <TableHead className="text-xs text-right">Query Similarity</TableHead>
              <TableHead className="text-xs text-right">Domain Novelty</TableHead>
              <TableHead className="text-xs text-right">Novelty</TableHead>
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
                    {bgc.accession}
                  </TableCell>
                  <TableCell className="text-xs">
                    {bgc.classification_path?.split('.')[0] || ''}
                  </TableCell>
                  <TableCell className="max-w-[150px] truncate text-xs">
                    <div className="flex items-center gap-1">
                      {bgc.is_type_strain && (
                        <Star className="h-3 w-3 flex-shrink-0 fill-amber-400 text-amber-400" />
                      )}
                      {bgc.source_name ?? "-"}
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {bgc.similarity_score.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {bgc.domain_novelty.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {bgc.novelty_score.toFixed(2)}
                  </TableCell>
                </TableRow>
              </BgcContextMenu>
            ))}
          </TableBody>
        </Table>
      </div>

      {pagination && pagination.total_pages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <span className="text-xs text-muted-foreground">
            {pagination.total_count} results
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
