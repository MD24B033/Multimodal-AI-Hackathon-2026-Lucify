/** The deployed API. Hardcoded so Vercel needs no environment variable — anything
 *  NEXT_PUBLIC_* has to be inlined at build time anyway, and getting the name wrong
 *  silently falls back to a host that is not there.
 *
 *  To run against a local backend, set NEXT_PUBLIC_BACKEND_URL in app/frontend/.env
 *  (that file is gitignored and never reaches Vercel). */
const DEPLOYED_API = "https://multimodal-ai-hackathon-2026-lucify-production.up.railway.app";

// An override that is present but blank would otherwise produce a relative "" base.
export const API_BASE =
  (process.env.NEXT_PUBLIC_BACKEND_URL || "").trim().replace(/\/+$/, "") || DEPLOYED_API;

const KEY_STORAGE = "companion.accessKey";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export function readAccessKey(): string | null {
  try {
    return window.localStorage.getItem(KEY_STORAGE);
  } catch {
    return null;
  }
}

export function writeAccessKey(key: string | null): void {
  try {
    if (key === null) window.localStorage.removeItem(KEY_STORAGE);
    else window.localStorage.setItem(KEY_STORAGE, key);
  } catch {
    return;
  }
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((item: { msg?: string }) => item.msg ?? "").join("; ");
    }
    return JSON.stringify(body);
  } catch {
    return response.statusText || "Request failed";
  }
}

function authHeaders(): Record<string, string> {
  const key = typeof window === "undefined" ? null : readAccessKey();
  return key ? { "X-Access-Key": key } : {};
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...authHeaders(),
      ...init?.headers,
    },
    cache: "no-store",
  });

  if (response.status === 401) {
    onUnauthorized?.();
    throw new ApiError(401, "Your access key is not valid. Sign in again.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json();
}

export const get = <T>(path: string) => api<T>(path);

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const del = (path: string) => api<void>(path, { method: "DELETE" });

export const upload = <T>(path: string, form: FormData) =>
  api<T>(path, { method: "POST", body: form });

export function mediaUrl(path: string): string {
  const key = typeof window === "undefined" ? null : readAccessKey();
  const url = new URL(`${API_BASE}${path}`);
  if (key) url.searchParams.set("access_key", key);
  return url.toString();
}

export async function signIn(key: string): Promise<{ name: string; student: unknown }> {
  const response = await fetch(`${API_BASE}/api/auth/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }
  return response.json();
}

export async function authRequired(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/auth/status`, { cache: "no-store" });
    if (!response.ok) return false;
    const body = (await response.json()) as { auth_required: boolean };
    return Boolean(body.auth_required);
  } catch {
    return false;
  }
}
