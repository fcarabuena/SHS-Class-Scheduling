export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "shs.token";

export const UNAUTHORIZED_EVENT = "shs:unauthorized";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage unavailable (private mode): the session just won't persist.
  }
}

/** Turns a FastAPI error body into one readable sentence. */
export function errorMessage(body: unknown, fallback: string): string {
  if (typeof body !== "object" || body === null || !("detail" in body)) return fallback;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item: { loc?: unknown[]; msg?: string }) => {
      const field = (item.loc ?? []).filter((p) => p !== "body").join(".");
      const message = (item.msg ?? "Invalid value").replace(/^Value error, /, "");
      return field ? `${field}: ${message}` : message;
    });
    if (parts.length) return parts.join("; ");
  }
  return fallback;
}

type Options = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  form?: FormData;
  params?: Record<string, string | number | boolean | undefined>;
};

async function request(path: string, options: Options): Promise<Response> {
  const url = new URL(API_URL + path);
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers,
      body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that the backend is running.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (response.status === 401 && token) {
      setToken(null);
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(response.status, errorMessage(body, `Request failed (${response.status})`));
  }
  return response;
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const response = await request(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Downloads a file that needs the auth header (so a plain link won't do). */
export async function download(path: string, filename: string): Promise<void> {
  const blob = await (await request(path, {})).blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(href);
}
