import { apiGet, apiPost, downloadBlob, ApiError } from "./client";
import type {
  AssessmentAccepted,
  AssessmentStatusResponse,
} from "./types";

const basePath =
  document.querySelector('meta[name="base-path"]')?.getAttribute("content") ??
  "";
const UPLOAD_API_BASE = `${basePath}/api/dashboard`;

export async function postAssemblyAssessment(
  assemblyId: number
): Promise<AssessmentAccepted> {
  return apiPost<AssessmentAccepted>(
    `/assess/assembly/${assemblyId}/`,
    {}
  );
}

export async function postBgcAssessment(
  bgcId: number
): Promise<AssessmentAccepted> {
  return apiPost<AssessmentAccepted>(`/assess/bgc/${bgcId}/`, {});
}

export async function fetchAssessmentStatus(
  taskId: string
): Promise<AssessmentStatusResponse> {
  return apiGet<AssessmentStatusResponse>(`/assess/status/${taskId}/`);
}

export async function fetchSimilarAssemblies(
  assemblyId: number
): Promise<number[]> {
  return apiGet<number[]>(`/assess/assembly/${assemblyId}/similar-assemblies/`);
}

export async function postUploadAssessment(
  type: "bgc" | "assembly",
  file: File,
): Promise<AssessmentAccepted> {
  const formData = new FormData();
  formData.append("type", type);
  formData.append("file", file);

  const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1];
  const headers: Record<string, string> = {};
  if (csrf) headers["X-CSRFToken"] = csrf;

  const response = await fetch(`${UPLOAD_API_BASE}/assess/upload/`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "Upload failed");
    throw new ApiError(response.status, text);
  }
  return response.json();
}

export async function exportAssessmentJson(taskId: string): Promise<void> {
  const response = await fetch(
    `${document.querySelector('meta[name="base-path"]')?.getAttribute("content") ?? ""}/api/dashboard/assess/export/${taskId}/`
  );
  if (!response.ok) throw new Error("Export failed");
  const blob = await response.blob();
  downloadBlob(blob, `assessment_${taskId.slice(0, 8)}.json`);
}
