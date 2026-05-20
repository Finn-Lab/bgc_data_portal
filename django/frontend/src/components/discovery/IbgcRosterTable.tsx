import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchIbgcIds, fetchIbgcRoster } from "@/api/ibgcs";
import type { IbgcRosterItem } from "@/api/types";
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
import { ChevronLeft, ChevronRight, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import {
  appliedFiltersToApiParams,
  isAppliedFiltersEmpty,
  useDiscoveryStore,
} from "@/stores/discovery-store";
import { MAX_SHORTLIST, useShortlistStore } from "@/stores/shortlist-store";
import { IbgcContextMenu } from "./IbgcContextMenu";
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
      { key: "label" as ColumnKey, label: "iBGC" },
      { key: "bitscore" as ColumnKey, label: "Bitscore" },
      { key: "best_hit" as ColumnKey, label: "Best hit" },
      ...BASE_TAIL_COLUMNS,
    ];
  }
  return [
    { key: "label" as ColumnKey, label: "iBGC" },
    { key: "similarity" as ColumnKey, label: "Sim." },
    ...BASE_TAIL_COLUMNS,
  ];
}

function fmtScore(v: number | null): string {
  return v == null ? "—" : v.toFixed(3);
}

export function IbgcRosterTable() {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [sortBy, setSortBy] = useState<SortKey>("novelty_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const setCompareIbgcId = useDiscoveryStore((s) => s.setCompareIbgcId);
  const compareIbgcId = useDiscoveryStore((s) => s.compareIbgcId);
  const resultIbgcIds = useDiscoveryStore((s) => s.resultIbgcIds);
  const searchSource = useDiscoveryStore((s) => s.searchSource);

  // When a Find-Similar-iBGCs query lands the result allow-list is in
  // similarity-descending order; default the roster sort to "similarity" so
  // the table mirrors that rank. The user can still click any other column
  // header to override. We trigger off ``searchSource`` so the same logic
  // covers any future similarity-emitting source.
  useEffect(() => {
    if (searchSource === "similar_ibgc") {
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
    resultIbgcIds,
    assetToken,
  );
  const hasActiveScope =
    !isAppliedFiltersEmpty(applied) ||
    resultIbgcIds !== null ||
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
      "ibgc-roster",
      page,
      pageSize,
      sortBy,
      order,
      filterParams,
    ],
    queryFn: () =>
      fetchIbgcRoster({
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

  const addBgcsBulk = useShortlistStore((s) => s.addBgcsBulk);
  const shortlistCount = useShortlistStore((s) => s.bgcs.length);
  const [isAddingAll, setIsAddingAll] = useState(false);

  const onAddAllToShortlist = async () => {
    if (isAddingAll) return;
    if (shortlistCount >= MAX_SHORTLIST) {
      toast.warning(`Shortlist is at the ${MAX_SHORTLIST} cap`);
      return;
    }
    setIsAddingAll(true);
    const toastId = toast.loading("Collecting iBGCs…");
    try {
      const resp = await fetchIbgcIds({
        sort_by: sortBy,
        order,
        ...filterParams,
      });
      if (resp.ids.length === 0) {
        toast.message("No iBGCs to add", { id: toastId });
        return;
      }
      const items = resp.ids.map((id) => ({ id, label: `iBGC-${id}` }));
      const { added, skipped } = addBgcsBulk(items);
      // ``skipped`` already includes capacity overflow within the returned
      // id batch; if the backend itself truncated the result set, prefix a
      // hint so the user knows the filter actually matched more.
      const truncatedNote = resp.truncated
        ? ` (filter matched ${resp.total_count.toLocaleString()} — only the top ${resp.ids.length.toLocaleString()} were considered)`
        : "";
      if (added === 0) {
        toast.warning(`Shortlist is at the ${MAX_SHORTLIST} cap`, { id: toastId });
      } else if (skipped > 0) {
        toast.success(
          `Added ${added} iBGCs; ${skipped} skipped — shortlist full${truncatedNote}`,
          { id: toastId },
        );
      } else {
        toast.success(`Added ${added} iBGCs to shortlist${truncatedNote}`, {
          id: toastId,
        });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Add all failed: ${msg}`, { id: toastId });
    } finally {
      setIsAddingAll(false);
    }
  };

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
      <div className="flex h-full flex-col" data-testid="ibgc-roster">
        <EmptyScopeMessage surface="iBGC roster" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col" data-testid="ibgc-roster">
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
                  Failed to load iBGCs.
                </TableCell>
              </TableRow>
            )}
            {!isLoading &&
              items.map((ibgc) => (
                <IbgcRosterRow
                  key={ibgc.id}
                  ibgc={ibgc}
                  selected={compareIbgcId === ibgc.id}
                  searchSource={searchSource}
                  similarityOverride={
                    resultSimilarityById?.[ibgc.id] ?? null
                  }
                  bestHitProteinOverride={
                    resultBestHitProteinById?.[ibgc.id] ?? null
                  }
                  onSelect={() => setCompareIbgcId(ibgc.id)}
                />
              ))}
            {!isLoading && items.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={COLUMNS.length}
                  className="text-center py-8 text-muted-foreground"
                >
                  No iBGCs found.
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
        onAddAllToShortlist={onAddAllToShortlist}
        addAllDisabled={
          isLoading ||
          isAddingAll ||
          (pagination?.total_count ?? 0) === 0 ||
          shortlistCount >= MAX_SHORTLIST
        }
        addAllBusy={isAddingAll}
      />
    </div>
  );
}

interface IbgcRosterRowProps {
  ibgc: IbgcRosterItem;
  selected: boolean;
  searchSource: string | null;
  /** Bitscore / Dice score from the active query, overlaid on the row
   *  because ``/ibgcs/roster/`` doesn't carry per-query metrics. */
  similarityOverride: number | null;
  bestHitProteinOverride: string | null;
  onSelect: () => void;
}

function IbgcRosterRow({
  ibgc,
  selected,
  searchSource,
  similarityOverride,
  bestHitProteinOverride,
  onSelect,
}: IbgcRosterRowProps) {
  const isSeq = searchSource === "sequence";
  const similarity = similarityOverride ?? ibgc.similarity_score;
  const bestHit = bestHitProteinOverride ?? ibgc.best_hit_protein_id;
  return (
    <IbgcContextMenu
      ibgcId={ibgc.id}
      ibgcLabel={ibgc.label}
      isPartial={ibgc.umap_projected}
      isAsset={ibgc.is_asset}
    >
      <TableRow
        onClick={onSelect}
        data-testid="ibgc-roster-row"
        data-ibgc-id={ibgc.id}
        data-is-asset={ibgc.is_asset || undefined}
        className={
          "cursor-pointer " +
          (ibgc.is_asset
            ? "bg-amber-50 dark:bg-amber-950/30 hover:bg-amber-100 dark:hover:bg-amber-950/50 "
            : "") +
          (selected ? "bg-accent" : "hover:bg-muted/40")
        }
      >
        <TableCell className="font-mono text-xs">
          {ibgc.label}
          {ibgc.is_asset && (
            <Badge
              className="ml-2 h-4 px-1 text-[10px] text-white border-transparent"
              style={{ backgroundColor: "#b45309" }}
              data-testid="asset-submitted-badge"
            >
              SUBMITTED
            </Badge>
          )}
          {ibgc.is_validated && (
            <Badge variant="default" className="ml-2 h-4 px-1 text-[10px]">
              Validated
            </Badge>
          )}
          {ibgc.is_type_strain && (
            <Badge
              className="ml-2 h-4 px-1 text-[10px] text-white border-transparent"
              style={{ backgroundColor: "#018786" }}
            >
              Type Strain
            </Badge>
          )}
          {ibgc.umap_projected && (
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
        <TableCell>{ibgc.size_kb.toFixed(1)}</TableCell>
        <TableCell>{fmtScore(ibgc.novelty_score)}</TableCell>
        <TableCell>{fmtScore(ibgc.domain_novelty)}</TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {ibgc.source_tools.join(", ")}
        </TableCell>
        <TableCell className="text-xs">
          {ibgc.parent_assembly_accession ?? "—"}
        </TableCell>
      </TableRow>
    </IbgcContextMenu>
  );
}

interface PaginationProps {
  page: number;
  totalPages: number;
  totalCount: number;
  onChange: (page: number) => void;
  onAddAllToShortlist: () => void;
  addAllDisabled: boolean;
  addAllBusy: boolean;
}

function Pagination({
  page,
  totalPages,
  totalCount,
  onChange,
  onAddAllToShortlist,
  addAllDisabled,
  addAllBusy,
}: PaginationProps) {
  return (
    <div className="flex items-center justify-between border-t px-3 py-1.5 text-xs">
      <span className="text-muted-foreground">
        {totalCount.toLocaleString()} iBGCs · page {page}/{totalPages}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1 px-2 text-xs"
          disabled={addAllDisabled}
          onClick={onAddAllToShortlist}
          data-testid="add-all-to-shortlist"
        >
          {addAllBusy ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Plus className="h-3 w-3" />
          )}
          Add all to shortlist
        </Button>
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
