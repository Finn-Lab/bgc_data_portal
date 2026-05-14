import { useState } from "react";
import {
  postNrbDomainQuery,
  fetchNrbSequenceQueryStatus,
} from "@/api/nrbs";
import { postSequenceQuery } from "@/api/queries";
import { useQueryStore } from "@/stores/query-store";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { useFilterStore } from "@/stores/filter-store";
import { ApiError } from "@/api/client";
import { toast } from "sonner";

/**
 * Hook that drives the Run Query button in the v2 dashboard.
 *
 * On every press it (a) snapshots the current filter-chip values into
 * ``discovery-store.appliedFilters`` — that's what the roster/maps key
 * off, so toggling chips alone does NOT refetch — and (b) resolves any
 * active advanced searches (domain conditions + sequence) into an NRB id
 * allow-list intersected with the filters.
 *
 * The chemical query path is not surfaced in v2 yet — it lives in P1.5b's
 * follow-up.
 */
export function useRunNrbQuery() {
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const domainConditions = useQueryStore((s) => s.domainConditions);
  const logic = useQueryStore((s) => s.logic);
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
    const f = useFilterStore.getState();
    setAppliedFilters({
      sourceNames: f.sourceNames,
      taxonomyPath: f.taxonomyPath,
      bgcClass: f.bgcClass,
      biomeLineage: f.biomeLineage,
      assemblyAccession: f.assemblyAccession,
      organism: f.search,
    });

    if (domainConditions.length === 0 && !sequenceQuery.trim()) {
      // Filters-only run: clear any prior advanced-query allow-list so the
      // roster reflects the new filter snapshot.
      setQueryResult(null, null);
      toast.success("Filters applied");
      return;
    }

    setIsRunning(true);
    try {
      const idSets: Set<number>[] = [];
      const similarities: Record<number, number> = {};

      // ── Domain branch ─────────────────────────────────────────────────
      if (domainConditions.length > 0) {
        const resp = await postNrbDomainQuery(
          {
            domains: domainConditions.map((c) => ({
              acc: c.acc,
              required: c.required,
            })),
            logic,
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

      // ── Sequence branch ───────────────────────────────────────────────
      if (sequenceQuery.trim()) {
        const accepted = await postSequenceQuery({
          sequence: sequenceQuery,
          min_bitscore: sequenceMinBitscore,
          min_pident: sequenceMinPident,
          min_qcov: sequenceMinQcov,
        });
        const taskId = accepted.task_id;
        // Poll until the task is ready (max ~30 attempts, 1s each).
        const seqResp = await pollSequenceTask(taskId, 30);
        const ids = seqResp.items.map((r) => r.id);
        idSets.push(new Set(ids));
        for (const item of seqResp.items) {
          if (item.similarity_score != null) {
            // Domain similarity is 1.0; prefer keeping the sequence
            // bitscore when both inputs hit the same NRB.
            similarities[item.id] = item.similarity_score;
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

      setQueryResult(intersection, similarities);
      toast.success(`Query returned ${intersection.length} NRB(s)`);
    } catch (e) {
      const err = e as Error;
      setError(err);
      toast.error(
        e instanceof ApiError
          ? `Query failed (${e.status}): ${e.message}`
          : `Query failed: ${err.message}`,
      );
    } finally {
      setIsRunning(false);
    }
  };

  return { run, isRunning, error };
}

async function pollSequenceTask(taskId: string, maxAttempts: number) {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      return await fetchNrbSequenceQueryStatus(taskId);
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) {
        await new Promise((r) => setTimeout(r, 1000));
        continue;
      }
      throw e;
    }
  }
  throw new Error("Sequence search timed out after 30s");
}
