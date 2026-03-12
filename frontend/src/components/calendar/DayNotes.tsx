import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchNotes } from '@/lib/api'
import { Skeleton } from '@/components/ui/skeleton'
import type { Note } from '@/types'

interface DayNotesProps {
  date: string
}

function formatTime(isoDate: string): string {
  const d = new Date(isoDate)
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

export function DayNotes({ date }: DayNotesProps) {
  const navigate = useNavigate()
  const [notes, setNotes] = useState<Note[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchNotes({ date, size: 100 })
      .then(res => setNotes(res.notes))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [date])

  const formattedDate = new Date(date + 'T00:00:00').toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })

  return (
    <div className="mt-6">
      <h3 className="mb-3 text-sm font-medium text-foreground">
        {formattedDate} ({notes.length} notes)
      </h3>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full rounded-md" />
          ))}
        </div>
      ) : (
        <div className="space-y-1">
          {notes.map(note => (
            <button
              key={note.id}
              onClick={() => navigate(`/note/${note.id}`)}
              className="flex w-full items-start gap-3 rounded-md px-3 py-2 text-left transition-colors hover:bg-accent"
            >
              <span className="shrink-0 text-xs text-muted-foreground">
                {formatTime(note.created_at)}
              </span>
              <span className="line-clamp-1 text-sm text-foreground">
                {note.content
                  ? note.content.replace(/^#{1,6}\s+/gm, '').replace(/[*_~`]/g, '').slice(0, 100)
                  : note.transcript?.slice(0, 100) || `[${note.media_type}]`}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
