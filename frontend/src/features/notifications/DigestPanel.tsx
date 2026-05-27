import { useQuery } from '@tanstack/react-query'
import { AlertCircle, TrendingUp, FileText, Clock } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchWeeklyDigest } from './api'
import { formatKRW, formatDate } from '@/lib/format'

/**
 * 주간 다이제스트 패널 — 우측 사이드시트/collapse 영역
 * - 미읽음 알림 카운트
 * - 7일 내 마감 마일스톤
 * - 지난 마일스톤
 * - 최근 7일 결제 (5건 max)
 * - 최근 7일 신규 계약 (5건 max)
 */
export function DigestPanel() {
  const { data: digest, isLoading } = useQuery({
    queryKey: ['digest', 'weekly'],
    queryFn: fetchWeeklyDigest,
    staleTime: 60 * 1000,
  })

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-20" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    )
  }

  if (!digest) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        다이제스트 로드 실패
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* 미읽음 알림 카운트 */}
      <Card className="p-4">
        <div className="flex items-center gap-3">
          <div className="rounded-full bg-amber-100 p-3">
            <AlertCircle className="h-5 w-5 text-amber-700" />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">읽지 않은 알림</p>
            <p className="text-2xl font-bold">{digest.unread_notifications}</p>
          </div>
        </div>
      </Card>

      {/* 7일 내 마감 마일스톤 */}
      {digest.upcoming_milestones.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Clock className="h-4 w-4" />
            예정된 마일스톤
          </h3>
          <div className="space-y-2">
            {digest.upcoming_milestones.map((m) => (
              <div
                key={m.id}
                className="rounded border border-blue-200 bg-blue-50 p-2 text-xs"
              >
                <div className="font-medium text-blue-900">{m.title}</div>
                <div className="mt-1 flex items-center justify-between">
                  <span className="text-blue-700">{m.project_name}</span>
                  <Badge variant="secondary">
                    D-{m.days_left}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 지난 마일스톤 */}
      {digest.overdue_milestones.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-3 text-sm font-semibold text-red-700">
            ⚠ 지난 마일스톤
          </h3>
          <div className="space-y-2">
            {digest.overdue_milestones.map((m) => (
              <div
                key={m.id}
                className="rounded border border-red-200 bg-red-50 p-2 text-xs"
              >
                <div className="font-medium text-red-900">{m.title}</div>
                <div className="mt-1 flex items-center justify-between">
                  <span className="text-red-700">{m.project_name}</span>
                  <span className="text-red-600">
                    {m.days_left > 0 ? `D-${m.days_left}` : `${Math.abs(m.days_left)}일 경과`}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 최근 결제 */}
      {digest.recent_payments.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <TrendingUp className="h-4 w-4" />
            최근 결제 (7일)
          </h3>
          <div className="space-y-2">
            {digest.recent_payments.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between rounded bg-gray-50 p-2 text-xs"
              >
                <div>
                  <div className="font-medium">{p.project_name}</div>
                  <div className="text-muted-foreground">{formatDate(p.date)}</div>
                </div>
                <div className="text-right font-semibold">{formatKRW(p.amount)}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 신규 계약 */}
      {digest.new_contracts.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <FileText className="h-4 w-4" />
            신규 계약 (7일)
          </h3>
          <div className="space-y-2">
            {digest.new_contracts.map((c) => (
              <div
                key={c.id}
                className="rounded bg-green-50 p-2 text-xs"
              >
                <div className="font-medium">{c.title}</div>
                <div className="mt-1 flex items-center justify-between">
                  <span className="text-muted-foreground">{c.project_name}</span>
                  <span className="text-green-700">{formatDate(c.date)}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 모든 섹션이 비었을 때 */}
      {digest.upcoming_milestones.length === 0 &&
        digest.overdue_milestones.length === 0 &&
        digest.recent_payments.length === 0 &&
        digest.new_contracts.length === 0 && (
          <Card className="p-4">
            <p className="text-center text-sm text-muted-foreground">
              표시할 항목이 없습니다.
            </p>
          </Card>
        )}
    </div>
  )
}
