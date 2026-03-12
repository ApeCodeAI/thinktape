import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { BarChart, Bar, XAxis, YAxis } from 'recharts'

interface TagBarChartProps {
  data: Array<{ tag: string; count: number }>
}

const chartConfig = {
  count: {
    label: 'Notes',
    color: 'var(--color-chart-5)',
  },
} satisfies ChartConfig

export function TagBarChart({ data }: TagBarChartProps) {
  const top20 = data.slice(0, 20)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top Tags</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-[400px] w-full">
          <BarChart data={top20} layout="vertical" accessibilityLayer>
            <XAxis type="number" tickLine={false} axisLine={false} />
            <YAxis
              type="category"
              dataKey="tag"
              tickLine={false}
              axisLine={false}
              width={100}
              tickMargin={4}
              tickFormatter={v => v.length > 12 ? v.slice(0, 12) + '...' : v}
            />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="count" fill="var(--color-count)" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
