/**
 * ThinkTape daemon API client. Base URL + device key come from config.ts.
 * On web (same origin) baseUrl is "" and no key is needed locally; on a phone
 * over LAN, baseUrl + device key are set in Settings and sent on every request.
 */
import { getConn } from "./config";

export type ItemType = "thought" | "bookmark" | "note";

export interface Item {
  id: string;
  created_at: string;
  updated_at: string;
  type: ItemType;
  source: string;
  status: string;
  tags: string[];
  bookmark_url: string | null;
  summary: string | null;
  has_audio: boolean;
  has_images: boolean;
  has_video: boolean;
  content: string;
  images: string[];
}

export interface ListResponse {
  items: Item[];
  limit: number;
  offset: number;
}

export interface Stats {
  total: number;
  today: number;
  by_type: Record<string, number>;
  by_tag: Record<string, number>;
}

function base(): string {
  return getConn().baseUrl;
}

/** Header map for authenticated requests (empty when no device key is set). */
export function authHeaders(): Record<string, string> {
  const k = getConn().deviceKey;
  return k ? { "X-ThinkTape-Key": k } : {};
}

/** Headers to pass to expo-image / expo-video / expo-audio for remote media. */
export function mediaHeaders(): Record<string, string> {
  return authHeaders();
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(base() + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = `${res.status} ${j.detail}`;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ListParams {
  type?: string;
  tag?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  list(p: ListParams = {}): Promise<ListResponse> {
    const qs = new URLSearchParams();
    if (p.type) qs.set("type", p.type);
    if (p.tag) qs.set("tag", p.tag);
    if (p.q) qs.set("q", p.q);
    qs.set("limit", String(p.limit ?? 30));
    qs.set("offset", String(p.offset ?? 0));
    return request<ListResponse>(`/api/items?${qs.toString()}`);
  },
  get: (id: string) => request<Item>(`/api/items/${id}`),
  create: (body: {
    content: string;
    type?: string;
    tags?: string[];
    bookmark_url?: string | null;
  }) =>
    request<Item>(`/api/items`, {
      method: "POST",
      body: JSON.stringify({ source: "app", ...body }),
    }),
  patch: (id: string, body: Partial<Pick<Item, "content" | "tags" | "status" | "type">>) =>
    request<Item>(`/api/items/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  remove: (id: string) => request<{ ok: boolean }>(`/api/items/${id}`, { method: "DELETE" }),
  stats: () => request<Stats>(`/api/stats`),
  tags: () => request<{ tags: string[] }>(`/api/tags`),
  pair: (name: string) =>
    request<{ name: string; key: string }>(`/api/pair`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  health: () => request<{ ok: boolean }>(`/healthz`),
  imageUrl: (id: string, name: string) => `${base()}/api/items/${id}/images/${name}`,
  audioUrl: (id: string) => `${base()}/api/items/${id}/audio`,
  videoUrl: (id: string) => `${base()}/api/items/${id}/video`,
};
