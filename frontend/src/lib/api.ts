import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number | null = null,
    public readonly code: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getApiBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? null;
}

/**
 * Fetch a fresh Supabase access token. getSession() transparently refreshes
 * an expired token, so every API call carries a valid Bearer token.
 */
export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) return null;
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

/**
 * Authenticated fetch against the FastAPI backend.
 * Returns the raw Response — callers stream (SSE) or `.json()` as needed.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const baseUrl = getApiBaseUrl();
  if (!baseUrl) {
    throw new ApiError("API is not configured.", null, "not_configured");
  }
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError("You are signed out.", 401, "no_session");
  }

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok && !response.body) {
    throw new ApiError(`Request failed (${response.status})`, response.status);
  }
  return response;
}

/** Convenience JSON wrapper for non-streaming endpoints. */
export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") message = body.detail;
    } catch {
      // keep default message
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}
