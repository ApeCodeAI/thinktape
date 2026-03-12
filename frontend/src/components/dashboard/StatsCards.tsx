import { Card, CardContent } from '@/components/ui/card'
import type { Stats } from '@/types'

interface StatsCardsProps {
  stats: Stats
}

export function StatsCards({ stats }: StatsCardsProps) {
  const items = [
    { label: 'Total Notes', value: stats.total },
    { label: 'This Month', value: stats.total_this_month },
    { label: 'Most Active Day', value: stats.most_active_day.date, sub: `${stats.most_active_day.count} notes` },
    { label: 'Unique Tags', value: stats.unique_tags },
  ]

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {items.map(item => (
        <Card key={item.label}>
          <CardContent className="p-4">
            <p className="text-2xl font-bold text-foreground">{item.value}</p>
            <p className="text-xs text-muted-foreground">{item.label}</p>
            {item.sub && (
              <p className="text-xs text-muted-foreground">{item.sub}</p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
