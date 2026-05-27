import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

import { api } from '@/lib/api-client'
import { queryKeys } from '@/lib/query-keys'
import { Skeleton } from '@/components/ui/skeleton'
import { Card } from '@/components/ui/card'

/**
 * /api/pm/portfolio/groups 응답 (PR #9에서 추가됨)
 * 프로젝트를 active/completed/lease/other로 분류
 */
interface PortfolioGroupsResponse {
  active: number
  completed: number
  lease: number
  other: number
}

export function PortfolioChart() {
  const groups = useQuery({
    queryKey: queryKeys.portfolio.groups,
    queryFn: () => api.get<PortfolioGroupsResponse>('/api/pm/portfolio/groups'),
    staleTime: 60 * 1000,
  })

  if (groups.isLoading) {
    return <Skeleton className="h-64" />
  }

  if (groups.isError) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        차트 로드 실패: {(groups.error as Error).message}
      </div>
    )
  }

  const chartData = groups.data
    ? [
        { name: '진행 중', value: groups.data.active, fill: '#3b82f6' },
        { name: '완료', value: groups.data.completed, fill: '#10b981' },
        { name: '임차', value: groups.data.lease, fill: '#f59e0b' },
        { name: '기타', value: groups.data.other, fill: '#6b7280' },
      ]
    : []

  const total = groups.data
    ? groups.data.active + groups.data.completed + groups.data.lease + groups.data.other
    : 0

  return (
    <Card className="p-6">
      <h3 className="mb-4 text-lg font-semibold">포트폴리오 구성</h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" />
          <YAxis />
          <Tooltip
            formatter={(value) => `${value}건`}
            contentStyle={{ backgroundColor: '#1f2937', border: 'none', borderRadius: '4px', color: '#fff' }}
          />
          <Bar dataKey="value" radius={[8, 8, 0, 0]}>
            {chartData.map((entry: { fill: string }, index: number) => (
              <Cell key={`cell-${index}`} fill={entry.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="mt-4 text-center text-sm text-muted-foreground">
        총 {total}건의 프로젝트
      </p>
    </Card>
  )
}
