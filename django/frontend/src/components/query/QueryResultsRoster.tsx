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
import { ChevronLeft, ChevronRight, Star } from "lucide-react";
import { cn } from "@/lib/utils";

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
  const { data, isLoading, page, setPage } = query;

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
      <div className="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Accession</TableHead>
              <TableHead className="text-xs">Class</TableHead>
              <TableHead className="text-xs">Organism</TableHead>
              <TableHead className="text-xs text-right">Relevance</TableHead>
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
                    {bgc.classification_l1}
                  </TableCell>
                  <TableCell className="max-w-[150px] truncate text-xs">
                    <div className="flex items-center gap-1">
                      {bgc.is_type_strain && (
                        <Star className="h-3 w-3 flex-shrink-0 fill-amber-400 text-amber-400" />
                      )}
                      {bgc.organism_name ?? bgc.assembly_accession ?? "-"}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <div className="h-2 w-12 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-query"
                          style={{
                            width: `${Math.round(bgc.relevance_score * 100)}%`,
                          }}
                        />
                      </div>
                      <span className="font-mono text-xs">
                        {bgc.relevance_score.toFixed(2)}
                      </span>
                    </div>
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
