import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { fetchProjectDetail, fetchProjectOverview } from './detail-api'
import type { ProjectOverview } from './detail-api'
import { queryKeys } from '@/lib/query-keys'
import { formatKRW } from '@/lib/format'

export function ProjectDetailPage({ projectId }: { projectId: number }) {
  const detail = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => fetchProjectDetail(projectId),
  })
  const overview = useQuery({
    queryKey: queryKeys.projects.overview(projectId),
    queryFn: () => fetchProjectOverview(projectId),
    enabled: !!detail.data,
  })

  if (detail.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (detail.isError) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        프로젝트 로드 실패: {(detail.error as Error).message}
        <div className="mt-2">
          <Link to="/overview">
            <Button variant="outline" size="sm">개요로 돌아가기</Button>
          </Link>
        </div>
      </div>
    )
  }

  const { project, trades, subcontracts_summary } = detail.data!
  const ov = overview.data ?? {}

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Link to="/overview" className="text-sm text-muted-foreground hover:underline">
              ← 개요
            </Link>
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{project.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {project.project_code && <Badge variant="outline">{project.project_code}</Badge>}
            {project.grade && <Badge>{project.grade}</Badge>}
            {project.category && <span>{project.category}</span>}
            {project.status && <span>· {project.status}</span>}
          </div>
        </div>
      </header>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">개요</TabsTrigger>
          <TabsTrigger value="members">멤버</TabsTrigger>
          <TabsTrigger value="budget">예산·하도급</TabsTrigger>
          <TabsTrigger value="milestones">마일스톤</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab overview={ov} loading={overview.isLoading} />
        </TabsContent>

        <TabsContent value="members">
          <MembersTab overview={ov} loading={overview.isLoading} />
        </TabsContent>

        <TabsContent value="budget">
          <Card>
            <CardHeader>
              <CardTitle>예산 / 하도급 요약</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-3 gap-4 text-sm">
              <Stat label="공종 수" value={trades.length} />
              <Stat label="하도급 계약 건" value={subcontracts_summary.count} />
              <Stat label="계약 총액" value={formatKRW(subcontracts_summary.total_contract)} />
              <Stat label="기성 누계" value={formatKRW(subcontracts_summary.total_paid)} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="milestones">
          <MilestonesTab overview={ov} loading={overview.isLoading} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
    </div>
  )
}

function OverviewTab({ overview, loading }: { overview: ProjectOverview; loading: boolean }) {
  if (loading) return <Skeleton className="h-48 w-full" />
  const items: { label: string; value: React.ReactNode }[] = [
    { label: '위치', value: overview.location || '-' },
    { label: '용도', value: overview.usage || '-' },
    { label: '규모', value: overview.scale || '-' },
    { label: '면적', value: overview.area ? `${overview.area} ㎡` : '-' },
    { label: '발주처', value: overview.client || '-' },
    { label: '시공사', value: overview.contractor || '-' },
    { label: '착공일', value: overview.start_date || '-' },
    { label: '준공일', value: overview.end_date || '-' },
    { label: '공기', value: overview.duration_days ? `${overview.duration_days}일` : '-' },
  ]
  return (
    <Card>
      <CardContent className="grid grid-cols-1 gap-4 pt-6 sm:grid-cols-2 md:grid-cols-3">
        {items.map((it) => (
          <div key={it.label}>
            <p className="text-xs text-muted-foreground">{it.label}</p>
            <p className="mt-1 text-sm font-medium">{it.value}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function MembersTab({ overview, loading }: { overview: ProjectOverview; loading: boolean }) {
  if (loading) return <Skeleton className="h-32 w-full" />
  const members = overview.members ?? []
  if (members.length === 0) {
    return <p className="text-sm text-muted-foreground">등록된 멤버가 없습니다.</p>
  }
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-muted-foreground">
          <tr>
            <th className="px-4 py-2 text-left font-medium">이름</th>
            <th className="px-4 py-2 text-left font-medium">역할</th>
            <th className="px-4 py-2 text-left font-medium">연락처</th>
          </tr>
        </thead>
        <tbody>
          {members.map((m, i) => (
            <tr key={i} className="border-t">
              <td className="px-4 py-2 font-medium">{m.name}</td>
              <td className="px-4 py-2 text-muted-foreground">{m.role ?? '-'}</td>
              <td className="px-4 py-2 tabular-nums">{m.phone ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MilestonesTab({ overview, loading }: { overview: ProjectOverview; loading: boolean }) {
  if (loading) return <Skeleton className="h-32 w-full" />
  const ms = overview.milestones ?? []
  if (ms.length === 0) {
    return <p className="text-sm text-muted-foreground">등록된 마일스톤이 없습니다.</p>
  }
  return (
    <div className="space-y-2">
      {ms.map((m, i) => (
        <Card key={i}>
          <CardContent className="flex items-center justify-between pt-4">
            <div>
              <p className="font-medium">{m.title}</p>
              <p className="text-xs text-muted-foreground">{m.due_date ?? '-'}</p>
            </div>
            <Badge variant={m.status === 'done' ? 'success' : 'outline'}>
              {m.status ?? 'pending'}
            </Badge>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
