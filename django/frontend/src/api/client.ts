const basePath =
  document.querySelector('meta[name="base-path"]')?.getAttribute("content") ??
  "";

const API_BASE = `${basePath}/api/dashboard`;

function getCsrfToken(): string | null {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match?.[1] ?? null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text().catch(() => "Unknown error");
    throw new ApiError(response.status, text);
  }
  return response.json() as Promise<T>;
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  const response = await fetch(url.toString());
  return handleResponse<T>(response);
}

export async function apiPost<T>(
  path: string,
  body: unknown
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const csrf = getCsrfToken();
  if (csrf) {
    headers["X-CSRFToken"] = csrf;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<T>(response);
}

export async function apiPostBlob(
  path: string,
  body: unknown
): Promise<Blob> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const csrf = getCsrfToken();
  if (csrf) {
    headers["X-CSRFToken"] = csrf;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "Unknown error");
    throw new ApiError(response.status, text);
  }
  return response.blob();
}

/**
 * POST a multipart/form-data payload (file uploads). Skips JSON serialisation
 * so the browser sets the multipart boundary header itself.
 */
export async function apiPostMultipart<T>(
  path: string,
  formData: FormData
): Promise<T> {
  const headers: Record<string, string> = {};
  const csrf = getCsrfToken();
  if (csrf) {
    headers["X-CSRFToken"] = csrf;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });
  return handleResponse<T>(response);
}

/** Fire-and-forget DELETE; returns true on 2xx. */
export async function apiDelete(path: string): Promise<boolean> {
  const headers: Record<string, string> = {};
  const csrf = getCsrfToken();
  if (csrf) {
    headers["X-CSRFToken"] = csrf;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers,
  });
  if (!response.ok && response.status !== 204) {
    const text = await response.text().catch(() => "Unknown error");
    throw new ApiError(response.status, text);
  }
  return true;
}

/** GET with custom headers — used to thread X-Asset-Token through ``/ibgcs/{id}/``. */
export async function apiGetWithHeaders<T>(
  path: string,
  extraHeaders: Record<string, string>,
  params?: Record<string, string | number | boolean | undefined>
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  const response = await fetch(url.toString(), { headers: extraHeaders });
  return handleResponse<T>(response);
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
