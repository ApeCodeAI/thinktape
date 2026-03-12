import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface NoteEditorProps {
  content: string
  tags: string
  onSave: (content: string, tags: string) => Promise<void>
  onCancel: () => void
}

export function NoteEditor({ content, tags, onSave, onCancel }: NoteEditorProps) {
  const [editContent, setEditContent] = useState(content)
  const [editTags, setEditTags] = useState(tags)
  const [saving, setSaving] = useState(false)

  async function handleSave() {
    setSaving(true)
    try {
      await onSave(editContent, editTags)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <textarea
        className="min-h-[200px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        value={editContent}
        onChange={e => setEditContent(e.target.value)}
      />
      <Input
        placeholder="Tags (comma separated)"
        value={editTags}
        onChange={e => setEditTags(e.target.value)}
      />
      <div className="flex gap-2">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? 'Saving...' : 'Save'}
        </Button>
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
