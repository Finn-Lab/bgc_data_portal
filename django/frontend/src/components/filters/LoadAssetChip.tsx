import { useCallback, useEffect, useRef, useState } from "react";
import {
  evictAsset,
  fetchAssetStatus,
  uploadAsset,
  type AssetState,
  type AssetSummary,
} from "@/api/assets";
import { Button } from "@/components/ui/button";
import { useDiscoveryStore } from "@/stores/discovery-store";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Loader2, Package, Upload, X, AlertTriangle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

/**
 * Chip in the filter strip that lets a user upload an ephemeral asset
 * (BGC TSVs packed as ``.tar.gz`` / ``.tgz``). Once projected the asset
 * iBGCs appear at the top of the roster and on the maps under the
 * ``SUBMITTED`` badge until the user clicks the X to evict.
 *
 * State machine:
 *   idle   → click → choose file → uploading
 *   uploading → polling status → loaded / failed
 *   loaded → click X → evict → idle
 *   failed → click X → dismiss → idle
 */

const POLL_INTERVAL_MS = 1500;
// 1h matches CELERY_RESULT_EXPIRES — past that the projection task's
// result is evicted from the result backend so longer polling would
// spin in vain.
const POLL_HARD_CAP_MS = 60 * 60 * 1000;
const POLL_SLOW_NOTICE_MS = 2 * 60 * 1000;

type ChipState =
  | { kind: "idle" }
  | { kind: "uploading"; filename: string }
  | { kind: "polling"; filename: string; token: string; state: AssetState }
  | { kind: "loaded"; summary: AssetSummary }
  | { kind: "failed"; message: string };

export function LoadAssetChip() {
  const [state, setState] = useState<ChipState>({ kind: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);
  const pollTimer = useRef<number | undefined>(undefined);
  const pollStartRef = useRef<number>(0);
  const slowNoticeShownRef = useRef<boolean>(false);
  const slowToastIdRef = useRef<string | number | undefined>(undefined);

  const assetToken = useDiscoveryStore((s) => s.assetToken);
  const assetSummary = useDiscoveryStore((s) => s.assetSummary);
  const setAsset = useDiscoveryStore((s) => s.setAsset);
  const queryClient = useQueryClient();

  // Hydrate from the store on first mount — the chip stays loaded across
  // dashboard tab switches because the token lives in the global store.
  useEffect(() => {
    if (assetToken && assetSummary && state.kind === "idle") {
      setState({ kind: "loaded", summary: assetSummary });
    }
  }, [assetToken, assetSummary, state.kind]);

  const dismissSlowToast = useCallback(() => {
    if (slowToastIdRef.current !== undefined) {
      toast.dismiss(slowToastIdRef.current);
      slowToastIdRef.current = undefined;
    }
  }, []);

  const clearPolling = useCallback(() => {
    if (pollTimer.current !== undefined) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = undefined;
    }
    slowNoticeShownRef.current = false;
    dismissSlowToast();
  }, [dismissSlowToast]);

  useEffect(() => () => clearPolling(), [clearPolling]);

  const pollOnce = useCallback(
    async (token: string, filename: string) => {
      try {
        const resp = await fetchAssetStatus(token);
        if (resp.state === "SUCCESS" && resp.summary) {
          clearPolling();
          setAsset(token, resp.summary);
          setState({ kind: "loaded", summary: resp.summary });
          // Asset roster/maps/count must re-fetch so the new rows surface.
          queryClient.invalidateQueries({ queryKey: ["ibgc-roster"] });
          queryClient.invalidateQueries({ queryKey: ["ibgc-umap"] });
          queryClient.invalidateQueries({ queryKey: ["ibgc-scatter"] });
          queryClient.invalidateQueries({ queryKey: ["ibgc-count"] });
          toast.success(
            `Asset projected: ${resp.summary.n_ibgcs} iBGC(s)`,
          );
          return;
        }
        if (resp.state === "FAILED") {
          clearPolling();
          setAsset(null, null);
          setState({ kind: "failed", message: resp.error ?? "Unknown error" });
          toast.error(`Asset projection failed: ${resp.error ?? "unknown"}`);
          return;
        }
        const elapsed = Date.now() - pollStartRef.current;
        if (elapsed > POLL_HARD_CAP_MS) {
          clearPolling();
          setAsset(null, null);
          setState({
            kind: "failed",
            message: "Projection exceeded the 1-hour limit",
          });
          toast.error("Asset projection timed out");
          return;
        }
        if (!slowNoticeShownRef.current && elapsed > POLL_SLOW_NOTICE_MS) {
          slowNoticeShownRef.current = true;
          slowToastIdRef.current = toast.message(
            "Still projecting… large assets can take several minutes. Keep this tab open.",
            {
              duration: Infinity,
              action: {
                label: "Cancel",
                onClick: () => {
                  clearPolling();
                  evictAsset(token).catch(() => {
                    /* tolerate — TTL will reap it */
                  });
                  setAsset(null, null);
                  setState({ kind: "idle" });
                },
              },
            },
          );
        }
        setState({
          kind: "polling",
          filename,
          token,
          state: resp.state,
        });
        pollTimer.current = window.setTimeout(
          () => pollOnce(token, filename),
          POLL_INTERVAL_MS,
        );
      } catch (e) {
        clearPolling();
        const msg = e instanceof Error ? e.message : String(e);
        setAsset(null, null);
        setState({ kind: "failed", message: msg });
      }
    },
    [clearPolling, queryClient, setAsset],
  );

  const onPickFile: React.ChangeEventHandler<HTMLInputElement> = async (e) => {
    const file = e.target.files?.[0];
    e.currentTarget.value = "";
    if (!file) return;

    // Evict any previously loaded asset so the chip occupies a single slot.
    if (assetToken) {
      try {
        await evictAsset(assetToken);
      } catch {
        /* tolerate — TTL will reap it eventually */
      }
      setAsset(null, null);
    }

    setState({ kind: "uploading", filename: file.name });
    try {
      const resp = await uploadAsset(file);
      pollStartRef.current = Date.now();
      setState({
        kind: "polling",
        filename: file.name,
        token: resp.token,
        state: "PENDING",
      });
      pollOnce(resp.token, file.name);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setState({ kind: "failed", message: msg });
      toast.error(`Upload failed: ${msg}`);
    }
  };

  const onEvict = useCallback(async () => {
    clearPolling();
    if (assetToken) {
      try {
        await evictAsset(assetToken);
      } catch {
        /* swallow */
      }
    }
    setAsset(null, null);
    setState({ kind: "idle" });
    queryClient.invalidateQueries({ queryKey: ["ibgc-roster"] });
    queryClient.invalidateQueries({ queryKey: ["ibgc-umap"] });
    queryClient.invalidateQueries({ queryKey: ["ibgc-scatter"] });
    queryClient.invalidateQueries({ queryKey: ["ibgc-count"] });
  }, [assetToken, clearPolling, queryClient, setAsset]);

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".tar.gz,.tgz,application/gzip,application/x-gzip,application/x-tar"
        className="hidden"
        onChange={onPickFile}
        data-testid="asset-file-input"
      />
      {state.kind === "idle" && (
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1 text-xs"
          onClick={() => inputRef.current?.click()}
          data-testid="load-asset-button"
        >
          <Upload className="h-3 w-3" />
          Load Asset
        </Button>
      )}
      {(state.kind === "uploading" || state.kind === "polling") && (
        <div className="flex h-7 items-center gap-1.5 rounded-md border border-dashed bg-muted/50 px-2 text-xs">
          <Loader2 className="h-3 w-3 animate-spin" />
          <span className="font-medium">{state.filename}</span>
          <span className="text-muted-foreground">
            {state.kind === "uploading"
              ? "uploading…"
              : state.state === "PENDING"
                ? "queued…"
                : "projecting…"}
          </span>
        </div>
      )}
      {state.kind === "loaded" && (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex h-7 items-center gap-1.5 rounded-md border bg-primary/10 px-2 text-xs">
                <Package className="h-3 w-3 text-primary" />
                <span className="font-medium">
                  {state.summary.assembly_accession}
                </span>
                <span className="text-muted-foreground">
                  · {state.summary.n_ibgcs} iBGC
                  {state.summary.n_ibgcs === 1 ? "" : "s"}
                </span>
                <button
                  onClick={onEvict}
                  className="ml-1 rounded p-0.5 hover:bg-muted"
                  data-testid="asset-evict"
                  aria-label="Remove asset"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            </TooltipTrigger>
            <TooltipContent>
              {state.summary.organism || "Submitted asset"}
              {!state.summary.projected && (
                <div className="mt-0.5 text-xs text-yellow-500">
                  Not projected (no clustering run available)
                </div>
              )}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}
      {state.kind === "failed" && (
        <div className="flex h-7 items-center gap-1.5 rounded-md border border-destructive/50 bg-destructive/10 px-2 text-xs">
          <AlertTriangle className="h-3 w-3 text-destructive" />
          <span
            className="max-w-[180px] truncate text-destructive"
            title={state.message}
          >
            {state.message}
          </span>
          <button
            onClick={() => setState({ kind: "idle" })}
            className="ml-1 rounded p-0.5 hover:bg-destructive/20"
            aria-label="Dismiss"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}
    </>
  );
}
