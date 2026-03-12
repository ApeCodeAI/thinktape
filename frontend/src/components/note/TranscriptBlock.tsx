import { useState } from 'react'

interface TranscriptBlockProps {
  transcript: string
}

export function TranscriptBlock({ transcript }: TranscriptBlockProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-lg border border-border">
      <button
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-foreground"
        onClick={() => setExpanded(!expanded)}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`transition-transform ${expanded ? 'rotate-90' : ''}`}
        >
          <path d="m9 18 6-6-6-6" />
        </svg>
        Transcript
      </button>
      {expanded && (
        <div className="border-t border-border px-4 py-3 text-sm leading-relaxed text-muted-foreground">
          {transcript}
        </div>
      )}
    </div>
  )
}
