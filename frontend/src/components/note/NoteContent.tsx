import { useMemo } from 'react'
import { renderMarkdown } from '@/lib/markdown'

interface NoteContentProps {
  content: string
}

export function NoteContent({ content }: NoteContentProps) {
  const html = useMemo(() => renderMarkdown(content), [content])

  return (
    <div
      className="prose prose-sm max-w-none dark:prose-invert prose-headings:text-foreground prose-a:text-primary prose-code:rounded prose-code:bg-muted prose-code:px-1.5 prose-code:py-0.5 prose-code:text-sm prose-pre:bg-muted prose-pre:text-foreground"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
