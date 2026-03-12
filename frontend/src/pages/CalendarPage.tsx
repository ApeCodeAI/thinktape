import { useState, useEffect } from 'react'
import { fetchCalendar } from '@/lib/api'
import { CalendarGrid } from '@/components/calendar/CalendarGrid'
import { DayNotes } from '@/components/calendar/DayNotes'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { CalendarData } from '@/types'

export default function CalendarPage() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [data, setData] = useState<CalendarData | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedDate, setSelectedDate] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setSelectedDate(null)
    fetchCalendar(year, month)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [year, month])

  function prevMonth() {
    if (month === 1) {
      setYear(y => y - 1)
      setMonth(12)
    } else {
      setMonth(m => m - 1)
    }
  }

  function nextMonth() {
    if (month === 12) {
      setYear(y => y + 1)
      setMonth(1)
    } else {
      setMonth(m => m + 1)
    }
  }

  const monthName = new Date(year, month - 1).toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric',
  })

  return (
    <div className="py-6">
      {/* Month navigation */}
      <div className="mb-6 flex items-center justify-between">
        <Button variant="ghost" size="icon" onClick={prevMonth}>
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </Button>
        <h2 className="text-lg font-semibold">{monthName}</h2>
        <Button variant="ghost" size="icon" onClick={nextMonth}>
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m9 18 6-6-6-6" />
          </svg>
        </Button>
      </div>

      {/* Calendar grid */}
      <Card>
        <CardContent className="p-4">
          {loading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : data ? (
            <CalendarGrid
              year={year}
              month={month}
              days={data.days}
              selectedDate={selectedDate}
              onSelectDate={setSelectedDate}
            />
          ) : (
            <p className="py-12 text-center text-muted-foreground">Failed to load calendar</p>
          )}
        </CardContent>
      </Card>

      {/* Day notes */}
      {selectedDate && <DayNotes date={selectedDate} />}
    </div>
  )
}
