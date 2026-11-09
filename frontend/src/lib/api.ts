/**
 * Fetch wrapper for the Kaagaz API. Adds the JWT, parses the API's error shape
 * ({ error: { code, message, details, request_id } }) into ApiError, and turns network failures and
 * free-tier cold starts into readable messages.
 */

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://localhost:8000';

const TOKEN_KEY = 'kaagaz.token';

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode): the session lasts until reload */
  }
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

let onUnauthorized: (() => void) | undefined;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

type Options = { method?: string; body?: unknown; form?: FormData; auth?: boolean; raw?: boolean };

async function request(path: string, options: Options): Promise<Response> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  const token = getToken();
  if (options.auth !== false && token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: options.method ?? (options.body !== undefined || options.form ? 'POST' : 'GET'),
      headers,
      body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
    });
  } catch {
    throw new ApiError(0, 'network', 'Could not reach the server. The free-tier API may be waking up; please retry in a minute.');
  }
  if (!res.ok) {
    let err: { code?: string; message?: string; details?: unknown; request_id?: string } = {};
    try {
      err = (await res.json()).error ?? {};
    } catch {
      /* not JSON (e.g. a proxy error page) */
    }
    if (res.status === 401 && options.auth !== false) onUnauthorized?.();
    throw new ApiError(res.status, err.code ?? 'http_error', err.message ?? `Request failed (${res.status})`, err.details, err.request_id);
  }
  return res;
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const res = await request(path, options);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function apiBlob(path: string, options: Options = {}): Promise<Blob> {
  return (await request(path, options)).blob();
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong';
}
