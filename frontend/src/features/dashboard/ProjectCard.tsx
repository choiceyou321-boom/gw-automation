import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { PortfolioRow } from '@/features/projects/api'
import { formatKRW, formatPercent } from '@/lib/format'

const GRADE_TONE: Record<string, 'default' | 'success' | 'warning' | 'destructive' | 'secondary'> = {
  A: 'success',
  B: 'default',
  C: 'warning',
  D: 'destructive',
}

export function ProjectCard({ row }: { row: PortfolioRow }) {
  const grade = (row.grade ?? '-').toString().trim()
  const tone = GRADE_TONE[grade] ?? 'secondary'
  const collRate = row.coll_rate ?? 0
  const paidRate = row.payment_limit
    ? Math.round((row.total_paid / row.payment_limit) * 100)
    : 0
  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="line-clamp-2 text-sm">{row.name}</CardTitle>
          <Badge variant={tone}>{grade}</Badge>
        </div>
        <p className="text-xs text-muted-foreground">{row.category || '-'}</p>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        <Row label="수주액" value={formatKRW(row.total_order)} />
        <Row label="실행예산" value={formatKRW(row.execution_budget)} />
        <Row
          label="이익률"
          value={formatPercent(row.profit_rate)}
          accent={(row.profit_rate ?? 0) < 0 ? 'destructive' : 'positive'}
        />
        <div className="flex items-center justify-between border-t pt-2">
          <span className="text-muted-foreground">수금</span>
          <div className="flex items-center gap-2">
            <span className="tabular-nums">{formatKRW(row.coll_collected)}</span>
            <Badge variant={collRate >= 90 ? 'success' : collRate >= 50 ? 'default' : 'secondary'}>
              {formatPercent(collRate, 0)}
            </Badge>
          </div>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">지급</span>
          <div className="flex items-center gap-2">
            <span className="tabular-nums">{formatKRW(row.total_paid)}</span>
            <Badge variant="outline">{paidRate}%</Badge>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function Row({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent?: 'positive' | 'destructive'
}) {
  const cls =
    accent === 'destructive'
      ? 'text-destructive'
      : accent === 'positive'
        ? 'text-emerald-600'
        : ''
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={`tabular-nums font-medium ${cls}`}>{value}</span>
    </div>
  )
}
