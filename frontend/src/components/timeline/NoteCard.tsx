import { useNavigate } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { Note } from '@/types'

interface NoteCardProps {
  note: Note
  onTagClick?: (tag: string) => void
}

const typeColors: Record<string, string> = {
  text: 'bg-secondary text-secondary-foreground',
  image: 'bg-chart-3/20 text-chart-1',
  video: 'bg-chart-4/20 text-chart-2',
  audio: 'bg-chart-5/20 text-chart-5',
}

function formatTime(isoDate: string): string {
  const d = new Date(isoDate)
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function getPreviewText(content: string | null): string {
  if (!content) return ''
  // Strip markdown syntax for preview
  return content
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_~`]/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '')
    .slice(0, 200)
}

export function NoteCard({ note, onTagClick }: NoteCardProps) {
  const navigate = useNavigate()
  const tags = note.tags ? note.tags.split(',').filter(Boolean) : []
  const imageAttachments = note.attachments.filter(a => a.media_type === 'image')

  return (
    <Card
      className="cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-md"
      onClick={() => navigate(`/note/${note.id}`)}
    >
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            {/* Meta row */}
            <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">{formatTime(note.created_at)}</span>
              <Badge variant="secondary" className={typeColors[note.media_type] || ''}>
                {note.media_type}
              </Badge>
              <span className="text-xs text-muted-foreground">{note.source}</span>
              {tags.map(tag => (
                <Badge
                  key={tag}
                  variant="outline"
                  className="cursor-pointer hover:bg-primary hover:text-primary-foreground"
                  onClick={e => {
                    e.stopPropagation()
                    onTagClick?.(tag)
                  }}
                >
                  #{tag}
                </Badge>
              ))}
            </div>
            {/* Content preview */}
            {note.content && (
              <p className="line-clamp-3 text-sm leading-relaxed text-foreground">
                {getPreviewText(note.content)}
              </p>
            )}
            {note.transcript && !note.content && (
              <p className="line-clamp-3 text-sm italic leading-relaxed text-muted-foreground">
                {note.transcript.slice(0, 200)}
              </p>
            )}
          </div>
          {/* Image thumbnails */}
          {imageAttachments.length > 0 && (
            <div className="flex shrink-0 gap-1">
              {imageAttachments.slice(0, 2).map(att => (
                <img
                  key={att.id}
                  src={`/${att.file_path}`}
                  alt=""
                  className="h-16 w-16 rounded-md object-cover"
                  loading="lazy"
                />
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
