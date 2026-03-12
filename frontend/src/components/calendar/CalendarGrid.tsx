import { cn } from '@/lib/utils'

interface CalendarGridProps {
  year: number
  month: number
  days: Record<string, number>
  selectedDate: string | null
  onSelectDate: (date: string) => void
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate()
}

function getFirstDayOfWeek(year: number, month: number): number {
  // 0=Sunday, we want 0=Monday
  const day = new Date(year, month - 1, 1).getDay()
  return day === 0 ? 6 : day - 1
}

export function CalendarGrid({ year, month, days, selectedDate, onSelectDate }: CalendarGridProps) {
  const daysInMonth = getDaysInMonth(year, month)
  const firstDay = getFirstDayOfWeek(year, month)
  const maxCount = Math.max(...Object.values(days), 1)

  const weekDays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

  function getDateString(day: number): string {
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
  }

  function getIntensity(count: number): string {
    if (count === 0) return ''
    const ratio = count / maxCount
    if (ratio < 0.25) return 'bg-primary/20'
    if (ratio < 0.5) return 'bg-primary/40'
    if (ratio < 0.75) return 'bg-primary/60'
    return 'bg-primary/80'
  }

  return (
    <div>
      {/* Weekday headers */}
      <div className="mb-1 grid grid-cols-7 gap-1">
        {weekDays.map(d => (
          <div key={d} className="py-2 text-center text-xs font-medium text-muted-foreground">
            {d}
          </div>
        ))}
      </div>

      {/* Day cells */}
      <div className="grid grid-cols-7 gap-1">
        {/* Empty cells for offset */}
        {Array.from({ length: firstDay }).map((_, i) => (
          <div key={`empty-${i}`} />
        ))}

        {/* Day cells */}
        {Array.from({ length: daysInMonth }).map((_, i) => {
          const day = i + 1
          const dateStr = getDateString(day)
          const count = days[dateStr] || 0
          const isSelected = dateStr === selectedDate
          const today = new Date()
          const isToday =
            today.getFullYear() === year &&
            today.getMonth() + 1 === month &&
            today.getDate() === day

          return (
            <button
              key={day}
              onClick={() => count > 0 && onSelectDate(dateStr)}
              className={cn(
                'flex aspect-square flex-col items-center justify-center rounded-md text-sm transition-colors',
                count > 0 && 'cursor-pointer hover:ring-2 hover:ring-ring',
                count === 0 && 'cursor-default text-muted-foreground',
                isSelected && 'ring-2 ring-primary',
                isToday && 'font-bold',
                getIntensity(count),
              )}
            >
              <span>{day}</span>
              {count > 0 && (
                <span className="text-[10px] leading-none text-foreground">{count}</span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
