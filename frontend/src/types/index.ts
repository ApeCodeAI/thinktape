export interface Attachment {
  id: number
  file_path: string
  media_type: 'image' | 'video' | 'audio'
  file_size: number | null
  duration: number | null
}

export interface Note {
  id: number
  content: string | null
  media_type: 'text' | 'image' | 'video' | 'audio'
  file_path: string | null
  tags: string
  created_at: string
  display_date: string
  source: string
  source_id: string | null
  transcript: string | null
  transcribe_status: string
  is_forwarded: number
  forward_from: string | null
  is_deleted: number
  duration: number | null
  file_size: number | null
  attachments: Attachment[]
}

export interface NotesResponse {
  notes: Note[]
  total: number
  page: number
  size: number
  has_more: boolean
}

export interface Stats {
  total: number
  total_this_month: number
  most_active_day: { date: string; count: number }
  unique_tags: number
  by_type: Record<string, number>
  by_source: Record<string, number>
  by_month: Array<{ month: string; count: number }>
  top_tags: Array<{ tag: string; count: number }>
}

export interface CalendarData {
  year: number
  month: number
  days: Record<string, number>
}

export interface TagInfo {
  tag: string
  count: number
}
