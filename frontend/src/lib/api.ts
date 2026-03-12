import type { NotesResponse, Note, Stats, CalendarData, TagInfo } from '@/types'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options)
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

export async function fetchNotes(params: {
  page?: number
  size?: number
  type?: string
  tag?: string
  q?: string
  date?: string
} = {}): Promise<NotesResponse> {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.size) searchParams.set('size', String(params.size))
  if (params.type) searchParams.set('type', params.type)
  if (params.tag) searchParams.set('tag', params.tag)
  if (params.q) searchParams.set('q', params.q)
  if (params.date) searchParams.set('date', params.date)
  return request<NotesResponse>(`/api/notes?${searchParams}`)
}

export async function fetchNote(id: number): Promise<Note> {
  return request<Note>(`/api/notes/${id}`)
}

export async function createNote(data: { content: string; tags?: string }): Promise<Note> {
  return request<Note>('/api/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function updateNote(id: number, data: { content?: string; tags?: string }): Promise<Note> {
  return request<Note>(`/api/notes/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function deleteNote(id: number): Promise<void> {
  await fetch(`/api/notes/${id}`, { method: 'DELETE' })
}

export async function restoreNote(id: number): Promise<void> {
  await fetch(`/api/notes/${id}/restore`, { method: 'POST' })
}

export async function fetchStats(): Promise<Stats> {
  return request<Stats>('/api/stats')
}

export async function fetchCalendar(year: number, month: number): Promise<CalendarData> {
  return request<CalendarData>(`/api/calendar?year=${year}&month=${month}`)
}

export async function fetchTags(): Promise<TagInfo[]> {
  const data = await request<{ tags: TagInfo[] }>('/api/tags')
  return data.tags
}
