import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { NoteContent } from '@/components/note/NoteContent'
import { NoteEditor } from '@/components/note/NoteEditor'
import { MediaViewer } from '@/components/note/MediaViewer'
import { TranscriptBlock } from '@/components/note/TranscriptBlock'
import { fetchNote, updateNote, deleteNote, restoreNote } from '@/lib/api'
import type { Note } from '@/types'

export default function NotePage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [note, setNote] = useState<Note | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    fetchNote(Number(id))
      .then(setNote)
      .catch(() => setNote(null))
      .finally(() => setLoading(false))
  }, [id])

  async function handleSave(content: string, tags: string) {
    if (!note) return
    const updated = await updateNote(note.id, { content, tags })
    setNote(updated)
    setEditing(false)
  }

  async function handleDelete() {
    if (!note) return
    await deleteNote(note.id)
    navigate('/')
  }

  async function handleRestore() {
    if (!note) return
    await restoreNote(note.id)
    const refreshed = await fetchNote(note.id)
    setNote(refreshed)
  }

  if (loading) {
    return (
      <div className="py-6">
        <Skeleton className="mb-4 h-4 w-32" />
        <Card>
          <CardContent className="space-y-4 p-6">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </CardContent>
        </Card>
      </div>
    )
  }

  if (!note) {
    return (
      <div className="py-12 text-center">
        <p className="text-muted-foreground">Note not found</p>
        <Link to="/" className="mt-4 inline-block text-primary underline">
          Back to timeline
        </Link>
      </div>
    )
  }

  const tags = note.tags ? note.tags.split(',').filter(Boolean) : []
  const typeLabels: Record<string, string> = {
    text: 'Text', image: 'Image', video: 'Video', audio: 'Audio',
  }

  return (
    <div className="py-6">
      <Link to="/" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m12 19-7-7 7-7" /><path d="M19 12H5" />
        </svg>
        Back to timeline
      </Link>

      <Card>
        <CardContent className="space-y-6 p-6">
          {/* Meta info */}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">
              {new Date(note.created_at).toLocaleDateString('en-US', {
                year: 'numeric', month: 'short', day: 'numeric',
              })}
              {' '}
              {new Date(note.created_at).toLocaleTimeString('en-GB', {
                hour: '2-digit', minute: '2-digit',
              })}
            </span>
            <Badge variant="secondary">{typeLabels[note.media_type] || note.media_type}</Badge>
            <Badge variant="outline">{note.source}</Badge>
          </div>

          <Separator />

          {/* Content */}
          {editing ? (
            <NoteEditor
              content={note.content || ''}
              tags={note.tags}
              onSave={handleSave}
              onCancel={() => setEditing(false)}
            />
          ) : (
            note.content && <NoteContent content={note.content} />
          )}

          {/* Media */}
          {note.attachments.length > 0 && (
            <>
              <Separator />
              <MediaViewer attachments={note.attachments} />
            </>
          )}

          {/* Transcript */}
          {note.transcript && (
            <>
              <Separator />
              <TranscriptBlock transcript={note.transcript} />
            </>
          )}

          {/* Tags */}
          {tags.length > 0 && (
            <>
              <Separator />
              <div className="flex flex-wrap gap-2">
                {tags.map(tag => (
                  <Badge key={tag} variant="outline">#{tag}</Badge>
                ))}
              </div>
            </>
          )}

          {/* Actions */}
          <Separator />
          <div className="flex justify-end gap-2">
            {note.is_deleted ? (
              <Button variant="outline" onClick={handleRestore}>
                Restore
              </Button>
            ) : (
              <>
                {!editing && (
                  <Button variant="outline" onClick={() => setEditing(true)}>
                    Edit
                  </Button>
                )}
                <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
                  Delete
                </Button>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Delete confirmation dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete note?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This will soft-delete the note. You can restore it later.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
