import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { LineChart, Line, XAxis, YAxis, CartesianGrid } from 'recharts'

interface MonthlyChartProps {
  data: Array<{ month: string; count: number }>
}

const chartConfig = {
  count: {
    label: 'Notes',
    color: 'var(--color-chart-1)',
  },
} satisfies ChartConfig

export function MonthlyChart({ data }: MonthlyChartProps) {
  // Sort chronologically
  const sorted = [...data].sort((a, b) => a.month.localeCompare(b.month))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Monthly Trend</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-[250px] w-full">
          <LineChart data={sorted} accessibilityLayer>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="month"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              tickFormatter={v => v.slice(5)}
            />
            <YAxis tickLine={false} axisLine={false} tickMargin={8} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Line
              type="monotone"
              dataKey="count"
              stroke="var(--color-count)"
              strokeWidth={2}
              dot={{ r: 4 }}
            />
          </LineChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
