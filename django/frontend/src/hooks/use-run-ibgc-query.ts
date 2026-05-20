import { useState } from "react";
import {
  postIbgcDomainQuery,
  postIbgcArchitectureQuery,
  fetchIbgcSequenceQueryStatus,
} from "@/api/ibgcs";
import { postSequenceQuery } from "@/api/queries";
import { useQueryStore } from "@/stores/query-store";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { useFilterStore } from "@/stores/filter-store";
import { ApiError } from "@/api/client";
import { toast } from "sonner";

/**
 * Soft cap on how many iBGCs we propagate from a scored query into the
 * dashboard's roster + maps. Mirrors the server-side
 * ``DASHBOARD_RESULT_CAP`` so the maps don't bother downsampling further.
 * When more than this many iBGCs come back, we keep the top-N by score —
 * that's what users actually care about for similarity-driven queries.
 */
const QUERY_RESULT_CAP = 5_000;

/**
 * Hook that drives the Run Query button in the v2 dashboard.
 *
 * On every press it (a) snapshots the current filter-chip values into
 * ``discovery-store.appliedFilters`` — that's what the roster/maps key
 * off, so toggling chips alone does NOT refetch — and (b) resolves any
 * active advanced searches (domain conditions + sequence) into an iBGC id
 * allow-list intersected with the filters.
 *
 * The chemical query path is not surfaced in v2 yet — it lives in P1.5b's
 * follow-up.
 */
export function useRunIbgcQuery() {
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const domainConditions = useQueryStore((s) => s.domainConditions);
  const domainMode = useQueryStore((s) => s.domainMode);
  const architectureText = useQueryStore((s) => s.domainArchitectureText);
  const architectureWeight = useQueryStore((s) => s.architectureWeight);
  const sequenceQuery = useQueryStore((s) => s.sequenceQuery);
  const sequenceMinBitscore = useQueryStore((s) => s.sequenceMinBitscore);
  const sequenceMinPident = useQueryStore((s) => s.sequenceMinPident);
  const sequenceMinQcov = useQueryStore((s) => s.sequenceMinQcov);

  const setQueryResult = useDiscoveryStore((s) => s.setQueryResult);
  const setAppliedFilters = useDiscoveryStore((s) => s.setAppliedFilters);

  const run = async () => {
    setError(null);

    // Snapshot chip values → applied filters every time Run Query is
    // pressed, regardless of whether an advanced query is also active.
    // Every chip in FilterPanel must be represented here, otherwise its
    // value is silently discarded between presses.
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

    // Active "domain" surface depends on which mode the user picked.
    // In architecture mode we treat the textarea as the active input,
    // not the chip conditions (the UI hides the chips while in arch mode).
    const archAccs = architectureText
      .split(/[,\s]+/)
      .map((t) => t.trim())
      .filter((t) => t.length > 0);
    const archActive = domainMode === "architecture" && archAccs.length > 0;
    const booleanActive =
      domainMode !== "architecture" && domainConditions.length > 0;

    if (!booleanActive && !archActive && !sequenceQuery.trim()) {
      // Filters-only run: clear any prior advanced-query allow-list so the
      // roster reflects the new filter snapshot.
      setQueryResult(null, null, null, null, null, null);
      toast.success("Filters applied");
      return;
    }

    setIsRunning(true);
    const abortController = new AbortController();
    try {
      const idSets: Set<number>[] = [];
      const similarities: Record<number, number> = {};
      const bestHitProtein: Record<number, string> = {};
      const pident: Record<number, number> = {};
      const qcoverage: Record<number, number> = {};

      // ── Domain branch ─────────────────────────────────────────────────
      if (booleanActive) {
        const resp = await postIbgcDomainQuery(
          {
            domains: domainConditions.map((c) => ({
              acc: c.acc,
              required: c.required,
            })),
            logic: domainMode === "or" ? "or" : "and",
          },
          { page: 1, page_size: 500 },
        );
        const ids = resp.items.map((r) => r.id);
        idSets.push(new Set(ids));
        for (const item of resp.items) {
          if (item.similarity_score != null) {
            similarities[item.id] = item.similarity_score;
          }
        }
      }

      // ── Architecture branch (composite-Dice) ──────────────────────────
      if (archActive) {
        const resp = await postIbgcArchitectureQuery(
          {
            architecture: archAccs,
            weight: architectureWeight,
            k: 500,
          },
          1,
          500,
        );
        const ids = resp.items.map((r) => r.id);
        idSets.push(new Set(ids));
        for (const item of resp.items) {
          if (item.similarity_score != null) {
            similarities[item.id] = item.similarity_score;
          }
        }
      }

      // ── Sequence branch ───────────────────────────────────────────────
      if (sequenceQuery.trim()) {
        const accepted = await postSequenceQuery({
          sequence: sequenceQuery,
          min_bitscore: sequenceMinBitscore,
          min_pident: sequenceMinPident,
          min_qcov: sequenceMinQcov,
        });
        const taskId = accepted.task_id;
        // Poll with backoff until the task is ready. Budget matches the
        // Celery result TTL (CELERY_RESULT_EXPIRES, default 1h): polling
        // longer is pointless because AsyncResult silently returns
        // PENDING for evicted task ids. Past the slow-notice threshold
        // (~2 min) we surface a cancellable "still searching" toast so
        // the user can let go without keeping the tab open.
        const seqResp = await pollSequenceTask(taskId, abortController);
        const ids = seqResp.items.map((r) => r.id);
        idSets.push(new Set(ids));
        for (const item of seqResp.items) {
          if (item.similarity_score != null) {
            // Domain similarity is 1.0; prefer keeping the sequence
            // bitscore when both inputs hit the same iBGC.
            similarities[item.id] = item.similarity_score;
          }
          if (item.best_hit_protein_id) {
            bestHitProtein[item.id] = item.best_hit_protein_id;
          }
          if (item.best_pident != null) {
            pident[item.id] = item.best_pident;
          }
          if (item.best_qcoverage != null) {
            qcoverage[item.id] = item.best_qcoverage;
          }
        }
      }

      // Intersect across active branches; if only one branch ran, that's
      // already the result. (Mirrors legacy intersection semantics.)
      let intersection: number[] = [];
      if (idSets.length === 1) {
        intersection = [...idSets[0]!];
      } else if (idSets.length > 1) {
        const first = idSets[0]!;
        intersection = [...first].filter((id) =>
          idSets.slice(1).every((s) => s.has(id)),
        );
      }

      // Top-K clip by score: similarity-driven queries (architecture,
      // sequence, similar-iBGC) only carry useful information for the
      // highest-scoring hits. Sort by score desc and clip to
      // ``QUERY_RESULT_CAP`` so the downstream roster + maps inherit the
      // cap via the ``ibgc_ids`` allow-list without the server having to
      // sample. Boolean-domain queries get similarity_score=1.0 for every
      // hit so the sort is a no-op — they're effectively unsorted, which
      // is fine since the cap rarely bites there.
      if (intersection.length > QUERY_RESULT_CAP) {
        intersection.sort((a, b) => {
          const sa = similarities[a] ?? -Infinity;
          const sb = similarities[b] ?? -Infinity;
          return sb - sa;
        });
        intersection = intersection.slice(0, QUERY_RESULT_CAP);
      }

      // When sequence search is one of the branches, label the result
      // set as "sequence" so the roster shows bitscore + best-hit
      // protein columns. Domain-only runs keep the standard similarity
      // column. Mixed runs prefer the sequence label since that path
      // carries the more useful per-iBGC metadata.
      const source:
        | "sequence"
        | "domain"
        | "domain_architecture"
        | null = sequenceQuery.trim()
        ? "sequence"
        : archActive
          ? "domain_architecture"
          : booleanActive
            ? "domain"
            : null;
      setQueryResult(
        intersection,
        similarities,
        source,
        source === "sequence" ? bestHitProtein : null,
        source === "sequence" ? pident : null,
        source === "sequence" ? qcoverage : null,
      );
      toast.success(`Query returned ${intersection.length} iBGC(s)`);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        toast.info("Sequence search cancelled");
      } else {
        const err = e as Error;
        setError(err);
        toast.error(
          e instanceof ApiError
            ? `Query failed (${e.status}): ${e.message}`
            : `Query failed: ${err.message}`,
        );
      }
    } finally {
      setIsRunning(false);
    }
  };

  return { run, isRunning, error };
}

// 1h matches CELERY_RESULT_EXPIRES — past that the result is evicted
// and AsyncResult would return PENDING forever, so capping polling
// here is the actionable boundary, not a UX guess.
const SEQUENCE_POLL_HARD_CAP_MS = 60 * 60 * 1000;
const SEQUENCE_POLL_SLOW_NOTICE_MS = 2 * 60 * 1000;
const SEQUENCE_POLL_INITIAL_MS = 1000;
const SEQUENCE_POLL_MAX_MS = 5000;

async function pollSequenceTask(
  taskId: string,
  abortController: AbortController,
) {
  // The backend returns 503 while the task is PENDING (so the
  // dashboard stays responsive) and 200 when ready. We back off the
  // poll interval to avoid hammering the API during multi-minute runs
  // but stay responsive for short ones — the first hit lands at 1s.
  const start = Date.now();
  let waitMs = SEQUENCE_POLL_INITIAL_MS;
  let slowNoticeShown = false;
  let slowToastId: string | number | undefined;

  const dismissSlowToast = () => {
    if (slowToastId !== undefined) {
      toast.dismiss(slowToastId);
      slowToastId = undefined;
    }
  };

  while (Date.now() - start < SEQUENCE_POLL_HARD_CAP_MS) {
    if (abortController.signal.aborted) {
      dismissSlowToast();
      throw new DOMException("Sequence search cancelled", "AbortError");
    }
    try {
      const result = await fetchIbgcSequenceQueryStatus(taskId);
      dismissSlowToast();
      return result;
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) {
        if (
          !slowNoticeShown &&
          Date.now() - start > SEQUENCE_POLL_SLOW_NOTICE_MS
        ) {
          slowNoticeShown = true;
          slowToastId = toast.message(
            "Still searching… large protein queries can take several minutes. Keep this tab open.",
            {
              duration: Infinity,
              action: {
                label: "Cancel",
                onClick: () => abortController.abort(),
              },
            },
          );
        }
        await new Promise((r) => setTimeout(r, waitMs));
        waitMs = Math.min(SEQUENCE_POLL_MAX_MS, Math.round(waitMs * 1.5));
        continue;
      }
      dismissSlowToast();
      throw e;
    }
  }
  dismissSlowToast();
  throw new Error(
    "Sequence search exceeded the 1-hour result lifetime — retry with a shorter sequence or tighter filters.",
  );
}
