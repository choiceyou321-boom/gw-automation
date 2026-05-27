import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface KpiWidgetProps {
  title: string
  value: string | number
  hint?: string
  tone?: 'default' | 'positive' | 'warning' | 'destructive'
}

// v6: 색 미니멀화 — KPI 숫자는 무채색 기본, 위험만 rose-700
const TONE_CLASS: Record<NonNullable<KpiWidgetProps['tone']>, string> = {
  default: 'text-foreground',
  positive: 'text-foreground',
  warning: 'text-foreground',
  destructive: 'text-rose-700',
}

export function KpiWidget({ title, value, hint, tone = 'default' }: KpiWidgetProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={cn('text-2xl font-bold tabular-nums', TONE_CLASS[tone])}>
          {value}
        </div>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  )
}
