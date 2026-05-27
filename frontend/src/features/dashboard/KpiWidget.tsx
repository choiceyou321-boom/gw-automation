import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface KpiWidgetProps {
  title: string
  value: string | number
  hint?: string
  tone?: 'default' | 'positive' | 'warning' | 'destructive'
}

const TONE_CLASS: Record<NonNullable<KpiWidgetProps['tone']>, string> = {
  default: 'text-foreground',
  positive: 'text-emerald-600',
  warning: 'text-amber-600',
  destructive: 'text-destructive',
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
