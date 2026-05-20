import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNrbRoster } from "@/api/nrbs";
import type { NrbRosterItem } from "@/api/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import {
  appliedFiltersToApiParams,
  isAppliedFiltersEmpty,
  useDiscoveryStore,
} from "@/stores/discovery-store";
import { NrbContextMenu } from "./NrbContextMenu";
import { EmptyScopeMessage } from "./EmptyScopeMessage";

type SortKey =
  | "novelty_score"
  | "domain_novelty"
  | "size_kb"
  | "id"
  | "similarity";

type ColumnKey =
  | SortKey
  | "label"
  | "tools"
  | "assembly"
  | "similarity"
  | "bitscore"
  | "best_hit";

const BASE_TAIL_COLUMNS: { key: ColumnKey; label: string }[] = [
  { key: "size_kb", label: "Size (kb)" },
  { key: "novelty_score", label: "Novelty" },
  { key: "domain_novelty", label: "Dom. nov." },
  { key: "tools", label: "Sources" },
  { key: "assembly", label: "Assembly" },
];

function columnsFor(searchSource: string | null) {
  // Sequence-search swaps the Sim. column for a Bitscore column and adds
  // a Best hit column showing the protein_id of the winning CDS.
  if (searchSource === "sequence") {
    return [
      { key: "label" as ColumnKey, label: "NRB" },
      { key: "bitscore" as ColumnKey, label: "Bitscore" },
      { key: "best_hit" as ColumnKey, label: "Best hit" },
      ...BASE_TAIL_COLUMNS,
    ];
  }
  return [
    { key: "label" as ColumnKey, label: "NRB" },
    { key: "similarity" as ColumnKey, label: "Sim." },
    ...BASE_TAIL_COLUMNS,
  ];
}

function fmtScore(v: number | null): string {
  return v == null ? "—" : v.toFixed(3);
}

export function NrbRosterTable() {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [sortBy, setSortBy] = useState<SortKey>("novelty_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const setCompareNrbId = useDiscoveryStore((s) => s.setCompareNrbId);
  const compareNrbId = useDiscoveryStore((s) => s.compareNrbId);
  const resultNrbIds = useDiscoveryStore((s) => s.resultNrbIds);
  const searchSource = useDiscoveryStore((s) => s.searchSource);

  // When a Find-Similar-NRBs query lands the result allow-list is in
  // similarity-descending order; default the roster sort to "similarity" so
  // the table mirrors that rank. The user can still click any other column
  // header to override. We trigger off ``searchSource`` so the same logic
  // covers any future similarity-emitting source.
  useEffect(() => {
    if (searchSource === "similar_nrb") {
      setSortBy("similarity");
      setOrder("desc");
    }
  }, [searchSource]);
  const resultSimilarityById = useDiscoveryStore(
    (s) => s.resultSimilarityById,
  );
  const resultBestHitProteinById = useDiscoveryStore(
    (s) => s.resultBestHitProteinById,
  );
  const applied = useDiscoveryStore((s) => s.appliedFilters);
  const assetToken = useDiscoveryStore((s) => s.assetToken);

  const COLUMNS = columnsFor(searchSource);

  const filterParams = appliedFiltersToApiParams(
    applied,
    resultNrbIds,
    assetToken,
  );
  const hasActiveScope =
    !isAppliedFiltersEmpty(applied) ||
    resultNrbIds !== null ||
    assetToken !== null;

  // Reset to page 1 whenever the applied filter set or result allow-list
  // changes — otherwise a deep-page user could see an empty page after
  // narrowing filters.
  const filterKey = JSON.stringify(filterParams);
  useEffect(() => {
    setPage(1);
  }, [filterKey]);
  const { data, isLoading, isError } = useQuery({
    queryKey: [
      "nrb-roster",
      page,
      pageSize,
      sortBy,
      order,
      filterParams,
    ],
    queryFn: () =>
      fetchNrbRoster({
        page,
        page_size: pageSize,
        sort_by: sortBy,
        order,
        ...filterParams,
      }),
    enabled: hasActiveScope,
  });

  const items = data?.items ?? [];
  const pagination = data?.pagination;

  const toggleSort = (key: SortKey) => {
    if (key === sortBy) {
      setOrder(order === "desc" ? "asc" : "desc");
    } else {
      setSortBy(key);
      setOrder("desc");
    }
    setPage(1);
  };

  if (!hasActiveScope) {
    return (
      <div className="flex h-full flex-col" data-testid="nrb-roster">
        <EmptyScopeMessage surface="NRB roster" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col" data-testid="nrb-roster">
      <ScrollArea className="flex-1">
        <Table>
          <TableHeader className="sticky top-0 bg-card z-10">
            <TableRow>
              {COLUMNS.map((col) => {
                const sortable = (
                  [
                    "size_kb",
                    "novelty_score",
                    "domain_novelty",
                    "similarity",
                  ] as readonly string[]
                ).includes(col.key);
                return (
                  <TableHead
                    key={col.key}
                    className={
                      sortable ? "cursor-pointer select-none" : undefined
                    }
                    onClick={
                      sortable
                        ? () => toggleSort(col.key as SortKey)
                        : undefined
                    }
                  >
                    {col.label}
                    {sortable && sortBy === col.key && (
                      <span className="ml-1 text-xs">
                        {order === "desc" ? "▼" : "▲"}
                      </span>
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} className="text-center py-8">
                  <Loader2 className="inline h-4 w-4 animate-spin" /> Loading…
                </TableCell>
              </TableRow>
            )}
            {isError && (
              <TableRow>
                <TableCell
                  colSpan={COLUMNS.length}
                  className="text-center py-8 text-destructive"
                >
                  Failed to load NRBs.
                </TableCell>
              </TableRow>
            )}
            {!isLoading &&
              items.map((nrb) => (
                <NrbRosterRow
                  key={nrb.id}
                  nrb={nrb}
                  selected={compareNrbId === nrb.id}
                  searchSource={searchSource}
                  similarityOverride={
                    resultSimilarityById?.[nrb.id] ?? null
                  }
                  bestHitProteinOverride={
                    resultBestHitProteinById?.[nrb.id] ?? null
                  }
                  onSelect={() => setCompareNrbId(nrb.id)}
                />
              ))}
            {!isLoading && items.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={COLUMNS.length}
                  className="text-center py-8 text-muted-foreground"
                >
                  No NRBs found.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </ScrollArea>

      <Pagination
        page={page}
        totalPages={pagination?.total_pages ?? 1}
        totalCount={pagination?.total_count ?? 0}
        onChange={setPage}
      />
    </div>
  );
}

interface NrbRosterRowProps {
  nrb: NrbRosterItem;
  selected: boolean;
  searchSource: string | null;
  /** Bitscore / Dice score from the active query, overlaid on the row
   *  because ``/nrbs/roster/`` doesn't carry per-query metrics. */
  similarityOverride: number | null;
  bestHitProteinOverride: string | null;
  onSelect: () => void;
}

function NrbRosterRow({
  nrb,
  selected,
  searchSource,
  similarityOverride,
  bestHitProteinOverride,
  onSelect,
}: NrbRosterRowProps) {
  const isSeq = searchSource === "sequence";
  const similarity = similarityOverride ?? nrb.similarity_score;
  const bestHit = bestHitProteinOverride ?? nrb.best_hit_protein_id;
  return (
    <NrbContextMenu
      nrbId={nrb.id}
      nrbLabel={nrb.label}
      isPartial={nrb.umap_projected}
      isAsset={nrb.is_asset}
    >
      <TableRow
        onClick={onSelect}
        data-testid="nrb-roster-row"
        data-nrb-id={nrb.id}
        data-is-asset={nrb.is_asset || undefined}
        className={
          "cursor-pointer " +
          (nrb.is_asset
            ? "bg-amber-50 dark:bg-amber-950/30 hover:bg-amber-100 dark:hover:bg-amber-950/50 "
            : "") +
          (selected ? "bg-accent" : "hover:bg-muted/40")
        }
      >
        <TableCell className="font-mono text-xs">
          {nrb.label}
          {nrb.is_asset && (
            <Badge
              className="ml-2 h-4 px-1 text-[10px] text-white border-transparent"
              style={{ backgroundColor: "#b45309" }}
              data-testid="asset-submitted-badge"
            >
              SUBMITTED
            </Badge>
          )}
          {nrb.is_validated && (
            <Badge variant="default" className="ml-2 h-4 px-1 text-[10px]">
              Validated
            </Badge>
          )}
          {nrb.is_type_strain && (
            <Badge
              className="ml-2 h-4 px-1 text-[10px] text-white border-transparent"
              style={{ backgroundColor: "#018786" }}
            >
              Type Strain
            </Badge>
          )}
          {nrb.umap_projected && (
            <Badge variant="outline" className="ml-2 h-4 px-1 text-[10px]">
              projected
            </Badge>
          )}
        </TableCell>
        {isSeq ? (
          <>
            <TableCell className="font-mono">
              {similarity != null ? similarity.toFixed(1) : "—"}
            </TableCell>
            <TableCell className="font-mono text-xs">
              {bestHit ?? "—"}
            </TableCell>
          </>
        ) : (
          <TableCell className="font-mono">
            {similarity != null ? similarity.toFixed(3) : "—"}
          </TableCell>
        )}
        <TableCell>{nrb.size_kb.toFixed(1)}</TableCell>
        <TableCell>{fmtScore(nrb.novelty_score)}</TableCell>
        <TableCell>{fmtScore(nrb.domain_novelty)}</TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {nrb.source_tools.join(", ")}
        </TableCell>
        <TableCell className="text-xs">
          {nrb.parent_assembly_accession ?? "—"}
        </TableCell>
      </TableRow>
    </NrbContextMenu>
  );
}

interface PaginationProps {
  page: number;
  totalPages: number;
  totalCount: number;
  onChange: (page: number) => void;
}

function Pagination({ page, totalPages, totalCount, onChange }: PaginationProps) {
  return (
    <div className="flex items-center justify-between border-t px-3 py-1.5 text-xs">
      <span className="text-muted-foreground">
        {totalCount.toLocaleString()} NRBs · page {page}/{totalPages}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          disabled={page >= totalPages}
          onClick={() => onChange(page + 1)}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
