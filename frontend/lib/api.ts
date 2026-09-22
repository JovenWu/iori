"use client";

/* API client — JWT in localStorage, refresh-on-401, SSE stream parser. */

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const BASE = `${API}/api/v1`;

const ACCESS_KEY = "sa_access";
const REFRESH_KEY = "sa_refresh";
const USER_KEY = "sa_user";

export type User = {
  id: number;
  username: string;
  email: string | null;
  name: string | null;
  is_active: boolean;
};

export type Thread = {
  id: string;
  title: string | null;
  starred: boolean;
  first_answer_preview: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = { role: string; content: string };

export type ThreadDetail = Thread & { messages: ChatMessage[] };

export type Memory = {
  id: string;
  content: string;
  created_at: string;
  updated_at: string;
};

export type StreamEvent = {
  seq: number;
  type: "started" | "token" | "tool" | "done" | "stopped" | "error";
  data: unknown;
};

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_KEY);
}

export function getStoredUser(): User | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

function setTokens(access: string, refresh: string, user?: User | null) {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
  if (user !== undefined) {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(USER_KEY);
  }
}

export function storeAuthUser(user: User | null) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else localStorage.removeItem(USER_KEY);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

/** Login — throws ApiError on failure (the page renders the detail). */
export async function login(username: string, password: string): Promise<User> {
  const resp = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(resp.status, body.detail ?? "Login failed");
  }
  setTokens(body.access_token, body.refresh_token, body.user ?? null);
  return body.user as User;
}

export async function logout() {
  const token = getAccessToken();
  clearTokens();
  if (token) {
    await fetch(`${BASE}/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {});
  }
}

async function tryRefresh(): Promise<boolean> {
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return false;
  const resp = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  }).catch(() => null);
  if (!resp?.ok) return false;
  const body = await resp.json();
  setTokens(body.access_token, body.refresh_token);
  return true;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  retried = false,
): Promise<T> {
  const token = getAccessToken();
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (resp.status === 401 && !retried && (await tryRefresh())) {
    return apiFetch<T>(path, init, true);
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body.detail ?? `HTTP ${resp.status}`);
  }
  return resp.json();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export interface ThreadListPage {
  threads: Thread[];
  /** Pass back as `cursor` for the next page; null when the list is done. */
  next_cursor: string | null;
}

export const listThreads = (opts?: { limit?: number; cursor?: string }) => {
  const params = new URLSearchParams();
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.cursor) params.set("cursor", opts.cursor);
  const qs = params.toString();
  return apiFetch<ThreadListPage>(`/threads${qs ? `?${qs}` : ""}`);
};
export const getThread = (id: string) => apiFetch<ThreadDetail>(`/threads/${id}`);
export const deleteThread = (id: string) =>
  apiFetch<{ detail: string }>(`/threads/${id}`, { method: "DELETE" });
export const updateThread = (
  id: string,
  patch: { title?: string; starred?: boolean },
) =>
  apiFetch<Thread>(`/threads/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
export const stopThread = (id: string) =>
  apiFetch<{ stopped: boolean }>(`/threads/${id}/stop`, { method: "POST" });

export const getMe = () => apiFetch<User>("/users/me");

/** Raw GET stream — used by the sidebar's detached-run watcher, which just
 * drains the body until the server closes it. */
export function fetchThreadStream(id: string, signal: AbortSignal) {
  const token = getAccessToken();
  return fetch(`${BASE}/threads/${id}/stream`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
}

export const listMemories = () =>
  apiFetch<{ memories: Memory[]; count: number }>("/memories");
export const deleteMemory = (id: string) =>
  apiFetch<{ detail: string }>(`/memories/${id}`, { method: "DELETE" });

/** POST /chat/stream — yields parsed SSE events until the run finishes. */
export async function* streamChat(
  message: string,
  threadId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const token = getAccessToken();
  const resp = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ message, thread_id: threadId }),
    signal,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body.detail ?? `HTTP ${resp.status}`);
  }
  if (!resp.body) throw new ApiError(0, "No response body");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        for (const line of frame.split("\n")) {
          if (line.startsWith("data: ")) {
            yield JSON.parse(line.slice(6)) as StreamEvent;
          }
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}
