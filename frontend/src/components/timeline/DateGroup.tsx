interface DateGroupProps {
  date: string
}

function getRelativeDate(dateStr: string): string {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const target = new Date(dateStr + 'T00:00:00')
  const diffMs = today.getTime() - target.getTime()
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24))

  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays} days ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`
  return ''
}

export function DateGroup({ date }: DateGroupProps) {
  const relative = getRelativeDate(date)

  return (
    <div className="sticky top-14 z-10 -mx-4 bg-background/90 px-4 py-2 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-semibold text-foreground">{date}</h2>
        {relative && (
          <span className="text-xs text-muted-foreground">{relative}</span>
        )}
      </div>
    </div>
  )
}
