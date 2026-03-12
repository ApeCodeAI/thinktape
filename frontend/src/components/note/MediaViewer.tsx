import { useState } from 'react'
import type { Attachment } from '@/types'

interface MediaViewerProps {
  attachments: Attachment[]
}

export function MediaViewer({ attachments }: MediaViewerProps) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)

  if (attachments.length === 0) return null

  return (
    <div>
      <h3 className="mb-3 text-sm font-medium text-muted-foreground">Attachments</h3>
      <div className="space-y-3">
        {attachments.map(att => {
          if (att.media_type === 'image') {
            return (
              <img
                key={att.id}
                src={`/${att.file_path}`}
                alt=""
                className="max-h-96 cursor-pointer rounded-lg object-contain"
                onClick={() => setLightboxSrc(`/${att.file_path}`)}
              />
            )
          }
          if (att.media_type === 'video') {
            return (
              <video
                key={att.id}
                src={`/${att.file_path}`}
                controls
                className="max-h-96 w-full rounded-lg"
              />
            )
          }
          if (att.media_type === 'audio') {
            return (
              <audio
                key={att.id}
                src={`/${att.file_path}`}
                controls
                className="w-full"
              />
            )
          }
          return null
        })}
      </div>

      {/* Lightbox */}
      {lightboxSrc && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={() => setLightboxSrc(null)}
          onKeyDown={e => e.key === 'Escape' && setLightboxSrc(null)}
          role="button"
          tabIndex={0}
        >
          <img
            src={lightboxSrc}
            alt=""
            className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain"
            onClick={e => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  )
}
