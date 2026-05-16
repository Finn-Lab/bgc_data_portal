import {
  isAppliedFiltersEmpty,
  useDiscoveryStore,
} from "@/stores/discovery-store";
import { useFilterStore } from "@/stores/filter-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { toast } from "sonner";
import { Pin, Search, Plus, RefreshCw, Clipboard } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { fetchNrbArchitecture, postSimilarNrbQuery } from "@/api/nrbs";

export interface NrbActionItem {
  key:
    | "set-ref"
    | "find-similar"
    | "copy-architecture"
    | "add-shortlist"
    | "clear-add-shortlist";
  label: string;
  icon: LucideIcon;
  onClick: () => void;
  /** When true the item should render before this entry. */
  separatorBefore?: boolean;
  /** Item is rendered greyed-out and is non-interactive. */
  disabled?: boolean;
  /** Tooltip / hint shown alongside a disabled item (right-aligned). */
  disabledHint?: string;
}

interface UseNrbActionsOptions {
  /** When set to "reference", "Set as reference NRB" is shown disabled
   *  because this NRB is already pinned in the reference slot. */
  variant?: "reference" | "compare";
  /** When true the NRB is a partial (umap_projected) — find-similar is
   *  disabled because the backend rejects partial seeds. */
  isPartial?: boolean;
  /** When true the NRB is sourced from an uploaded asset (negative id).
   *  Find-similar / sequence-search are skipped per the locked scope. */
  isAsset?: boolean;
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function useNrbActions(
  nrbId: number,
  nrbLabel: string,
  options: UseNrbActionsOptions = {},
): NrbActionItem[] {
  const setReferenceNrbId = useDiscoveryStore((s) => s.setReferenceNrbId);
  const setQueryResult = useDiscoveryStore((s) => s.setQueryResult);
  const setAppliedFilters = useDiscoveryStore((s) => s.setAppliedFilters);
  const assetToken = useDiscoveryStore((s) => s.assetToken);
  const addBgc = useShortlistStore((s) => s.addBgc);
  const replaceBgcs = useShortlistStore((s) => s.replaceBgcs);

  const isReference = options.variant === "reference";
  const isPartial = options.isPartial === true;
  const isAsset = options.isAsset === true;

  const onSetRef = () => {
    setReferenceNrbId(nrbId);
    toast.success(`Pinned ${nrbLabel} as reference`);
  };

  const onFindSimilar = async () => {
    setReferenceNrbId(nrbId);
    // Re-snapshot the current filter-chip values into ``appliedFilters``
    // before the result lands. The roster/maps intersect ``nrb_ids`` with
    // ``appliedFilters``, and that snapshot is otherwise only updated by
    // the Run Query button — so without this step, clearing chips in the
    // UI would not affect a subsequent Find Similar run. Mirrors the
    // snapshot block in ``useRunNrbQuery.run``.
    const f = useFilterStore.getState();
    setAppliedFilters({
      sourceNames: f.sourceNames,
      detectorTools: f.detectorTools,
      assemblyType: f.assemblyType,
      taxonomyPath: f.taxonomyPath,
      bgcClass: f.bgcClass,
      gcfPath: f.gcfPath,
      chemontIds: f.chemontIds,
      biomeLineage: f.biomeLineage,
      bgcAccession: f.bgcAccession,
      assemblyAccession: f.assemblyAccession,
      assemblyIds: f.assemblyIds,
      organism: f.search,
    });
    const toastId = toast.loading(`Finding NRBs similar to ${nrbLabel}…`);
    try {
      const resp = await postSimilarNrbQuery(
        { nrb_id: nrbId, k: 100 },
        1,
        100,
      );
      const ids = resp.items.map((r) => r.id);
      const similarity: Record<number, number> = {};
      for (const item of resp.items) {
        if (item.similarity_score != null) {
          similarity[item.id] = item.similarity_score;
        }
      }
      setQueryResult(ids, similarity, "similar_nrb", null, null, null);
      // Detect filter chips still active in the Top Filters strip — the
      // roster intersects ``nrb_ids`` with those chips, which can silently
      // drop the visible row count below ``ids.length``. Surface that in
      // the toast description so the user knows where the rows went. Uses
      // the freshly-snapshotted ``appliedFilters`` so it reflects what the
      // user currently sees, not the previous Run Query state.
      const chipsActive = !isAppliedFiltersEmpty(
        useDiscoveryStore.getState().appliedFilters,
      );
      toast.success(`Found ${ids.length} similar NRB(s)`, {
        id: toastId,
        description: chipsActive
          ? "Top Filters chips still applied — clear them to see the full neighbourhood."
          : undefined,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Find similar failed: ${msg}`, { id: toastId });
    }
  };

  const onCopyArchitecture = async () => {
    const toastId = toast.loading(`Copying domain architecture…`);
    try {
      const resp = await fetchNrbArchitecture(nrbId, assetToken);
      if (resp.ordered_accs.length === 0) {
        toast.warning(
          `${nrbLabel} has no PFAM/NCBIFAM domains to copy`,
          { id: toastId },
        );
        return;
      }
      const text = resp.ordered_accs.join(", ");
      const ok = await copyToClipboard(text);
      if (ok) {
        toast.success(
          `Copied ${resp.ordered_accs.length} domains to clipboard`,
          { id: toastId },
        );
      } else {
        // Clipboard API blocked (insecure context, etc.) — surface the
        // string in the toast so the user can copy manually.
        toast.message(`Copy unavailable — here's the architecture:`, {
          id: toastId,
          description: text,
        });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Copy failed: ${msg}`, { id: toastId });
    }
  };

  const onAddToShortlist = () => {
    const ok = addBgc({ id: nrbId, label: nrbLabel });
    if (ok) toast.success(`Added ${nrbLabel} to shortlist`);
    else toast.warning("Shortlist is at the 100 cap");
  };

  const onClearAndAdd = () => {
    replaceBgcs({ id: nrbId, label: nrbLabel });
    toast.success(`Shortlist replaced with ${nrbLabel}`);
  };

  return [
    {
      key: "set-ref",
      label: "Set as reference NRB",
      icon: Pin,
      onClick: onSetRef,
      disabled: isReference,
      disabledHint: isReference ? "Already pinned" : undefined,
    },
    {
      key: "find-similar",
      label: "Find similar NRBs",
      icon: Search,
      onClick: onFindSimilar,
      disabled: isPartial || isAsset,
      disabledHint: isAsset
        ? "Submitted asset — out of scope"
        : isPartial
          ? "Partial NRB"
          : undefined,
    },
    {
      key: "copy-architecture",
      label: "Copy domain architecture",
      icon: Clipboard,
      onClick: onCopyArchitecture,
    },
    {
      key: "add-shortlist",
      label: "Add to shortlist",
      icon: Plus,
      onClick: onAddToShortlist,
      separatorBefore: true,
    },
    {
      key: "clear-add-shortlist",
      label: "Clear shortlist & add",
      icon: RefreshCw,
      onClick: onClearAndAdd,
    },
  ];
}
