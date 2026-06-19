export interface Item {
  id: string;
  created_at: string;
  updated_at: string;
  type: "thought" | "bookmark" | "note";
  source: string;
  status: "active" | "archived" | "deleted";
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

export interface ListParams {
  type?: string;
  tag?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface CreateItemPayload {
  content: string;
  type?: "thought" | "bookmark" | "note";
  source?: string;
  tags?: string[];
  bookmark_url?: string | null;
}

const BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}: ${text}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  list: async (params: ListParams = {}): Promise<ListResponse> => {
    const qs = new URLSearchParams();
    if (params.type) qs.set("type", params.type);
    if (params.tag) qs.set("tag", params.tag);
    if (params.q) qs.set("q", params.q);
    qs.set("limit", String(params.limit ?? 30));
    qs.set("offset", String(params.offset ?? 0));
    return request<ListResponse>(`/api/items?${qs.toString()}`);
  },
  get: (id: string) => request<Item>(`/api/items/${id}`),
  create: (body: CreateItemPayload) =>
    request<Item>(`/api/items`, { method: "POST", body: JSON.stringify(body) }),
  patch: (id: string, body: Partial<Item>) =>
    request<Item>(`/api/items/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`/api/items/${id}`, { method: "DELETE" }),
  stats: () => request<Stats>(`/api/stats`),
  tags: () => request<{ tags: string[] }>(`/api/tags`),

  audioUrl: (id: string) => `/api/items/${id}/audio`,
  videoUrl: (id: string) => `/api/items/${id}/video`,
  imageUrl: (id: string, name: string) => `/api/items/${id}/images/${encodeURIComponent(name)}`,
};
