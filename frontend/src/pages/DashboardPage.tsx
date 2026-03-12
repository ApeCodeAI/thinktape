import { useState, useEffect } from 'react'
import { fetchStats } from '@/lib/api'
import { StatsCards } from '@/components/dashboard/StatsCards'
import { MonthlyChart } from '@/components/dashboard/MonthlyChart'
import { TypePieChart } from '@/components/dashboard/TypePieChart'
import { TagBarChart } from '@/components/dashboard/TagBarChart'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { Stats } from '@/types'

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="space-y-6 py-6">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-lg border border-border p-4">
              <Skeleton className="mb-2 h-8 w-16" />
              <Skeleton className="h-3 w-20" />
            </div>
          ))}
        </div>
        <Skeleton className="h-[300px] w-full rounded-lg" />
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="py-12 text-center">
        <p className="text-muted-foreground">Failed to load stats</p>
      </div>
    )
  }

  return (
    <div className="space-y-6 py-6">
      <StatsCards stats={stats} />

      {/* Source distribution */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Sources:</span>
        {Object.entries(stats.by_source).map(([source, count]) => (
          <Badge key={source} variant="secondary">
            {source}: {count}
          </Badge>
        ))}
      </div>

      <MonthlyChart data={stats.by_month} />

      <div className="grid gap-6 md:grid-cols-2">
        <TypePieChart data={stats.by_type} />
        <TagBarChart data={stats.top_tags} />
      </div>
    </div>
  )
}
