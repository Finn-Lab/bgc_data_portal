import { apiDelete, apiGet, apiPostMultipart } from "./client";

/** Backend states for an ephemeral asset projection. */
export type AssetState =
  | "PENDING"
  | "RUNNING"
  | "SUCCESS"
  | "FAILED"
  | "UNKNOWN";

export interface AssetUploadAccepted {
  token: string;
  task_id: string;
}

export interface AssetSummary {
  token: string;
  uploaded_at: string;
  n_ibgcs: number;
  n_bgcs: number;
  assembly_accession: string;
  organism: string | null;
  source_label: string;
  clustering_run_id: number | null;
  projected: boolean;
  n_projected: number;
}

export interface AssetStatusResponse {
  state: AssetState;
  task_id?: string | null;
  progress?: Record<string, unknown> | null;
  error?: string | null;
  summary?: AssetSummary | null;
}

/** POST a ``.tar.gz`` / ``.tgz`` file; backend returns ``{token, task_id}``. */
export function uploadAsset(file: File): Promise<AssetUploadAccepted> {
  const form = new FormData();
  form.append("file", file, file.name);
  return apiPostMultipart<AssetUploadAccepted>("/assets/upload/", form);
}

/** Poll the projection state — returns ``UNKNOWN`` when the token has expired. */
export function fetchAssetStatus(token: string): Promise<AssetStatusResponse> {
  return apiGet<AssetStatusResponse>(`/assets/${encodeURIComponent(token)}/status/`);
}

/** Drop every Redis key for an asset token (user X-click on the chip). */
export function evictAsset(token: string): Promise<boolean> {
  return apiDelete(`/assets/${encodeURIComponent(token)}/`);
}
