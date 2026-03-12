import { useState, useEffect, useRef, useCallback } from 'react'
import { useNotes } from '@/hooks/use-notes'
import { FilterBar } from '@/components/timeline/FilterBar'
import { NoteCard } from '@/components/timeline/NoteCard'
import { DateGroup } from '@/components/timeline/DateGroup'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { createNote } from '@/lib/api'
import type { Note } from '@/types'

export default function TimelinePage() {
  const [type, setType] = useState('')
  const [tag, setTag] = useState('')
  const [q, setQ] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [newContent, setNewContent] = useState('')
  const [newTags, setNewTags] = useState('')
  const [creating, setCreating] = useState(false)

  const { notes, total, hasMore, loading, initialLoading, loadMore, refresh } = useNotes({
    type: type || undefined,
    tag: tag || undefined,
    q: q || undefined,
  })

  // Infinite scroll sentinel
  const sentinelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return

    const observer = new IntersectionObserver(
      entries => {
        if (entries[0].isIntersecting) loadMore()
      },
      { rootMargin: '200px' }
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [loadMore])

  // Group notes by display_date
  const grouped: [string, Note[]][] = []
  const seen = new Set<string>()
  for (const note of notes) {
    if (!seen.has(note.display_date)) {
      seen.add(note.display_date)
      grouped.push([note.display_date, []])
    }
    grouped[grouped.length - 1][1].push(note)
  }

  const handleTagClick = useCallback((clickedTag: string) => {
    setTag(clickedTag)
  }, [])

  async function handleCreate() {
    if (!newContent.trim()) return
    setCreating(true)
    try {
      await createNote({ content: newContent, tags: newTags })
      setDialogOpen(false)
      setNewContent('')
      setNewTags('')
      refresh()
    } catch {
      // ignore
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="py-6">
      <FilterBar
        type={type}
        tag={tag}
        q={q}
        total={total}
        onTypeChange={setType}
        onTagChange={setTag}
        onSearchChange={setQ}
      />

      <div className="mt-6 space-y-2">
        {initialLoading ? (
          Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="rounded-lg border border-border p-4">
              <div className="mb-2 flex gap-2">
                <Skeleton className="h-4 w-12" />
                <Skeleton className="h-4 w-16" />
              </div>
              <Skeleton className="mb-1 h-4 w-full" />
              <Skeleton className="mb-1 h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          ))
        ) : notes.length === 0 ? (
          <p className="py-12 text-center text-muted-foreground">No notes found</p>
        ) : (
          grouped.map(([date, dateNotes]) => (
            <div key={date}>
              <DateGroup date={date} />
              <div className="space-y-2">
                {dateNotes.map(note => (
                  <NoteCard key={note.id} note={note} onTagClick={handleTagClick} />
                ))}
              </div>
            </div>
          ))
        )}

        {/* Loading more */}
        {loading && !initialLoading && (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="rounded-lg border border-border p-4">
                <Skeleton className="mb-2 h-4 w-20" />
                <Skeleton className="mb-1 h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ))}
          </div>
        )}

        {/* Sentinel for infinite scroll */}
        <div ref={sentinelRef} />

        {!hasMore && notes.length > 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">No more notes</p>
        )}
      </div>

      {/* FAB - Create Note */}
      <Button
        className="fixed bottom-20 right-6 z-40 h-14 w-14 rounded-full shadow-lg md:bottom-6"
        size="icon"
        onClick={() => setDialogOpen(true)}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12h14" /><path d="M12 5v14" />
        </svg>
      </Button>

      {/* Create Note Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Note</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <textarea
              className="min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="Write something..."
              value={newContent}
              onChange={e => setNewContent(e.target.value)}
            />
            <Input
              placeholder="Tags (comma separated)"
              value={newTags}
              onChange={e => setNewTags(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={creating || !newContent.trim()}>
              {creating ? 'Creating...' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
