import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchInsights, generateInsights } from './api'
import { InsightCard } from './InsightCard'
import { queryKeys } from '@/lib/query-keys'
import { Sparkles } from 'lucide-react'

export function InsightsPanel() {
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)

  const queryClient = useQueryClient()

  const insights = useQuery({
    queryKey: queryKeys.insights.all,
    queryFn: fetchInsights,
    staleTime: 60 * 1000,
  })

  // 인사이트에서 추출한 프로젝트 목록
  const projectOptions = useMemo(() => {
    if (!insights.data?.projects) return []
    return Object.entries(insights.data.projects).map(([pid, { project_name }]) => ({
      id: parseInt(pid, 10),
      name: project_name,
    }))
  }, [insights.data])

  // 프로젝트 선택 셀렉트 컴포넌트
  const ProjectSelect = () => (
    <select
      value={selectedProjectId ?? ''}
      onChange={(e) => setSelectedProjectId(e.target.value ? Number(e.target.value) : null)}
      className="h-9 w-72 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <option value="">프로젝트를 선택해주세요</option>
      {projectOptions.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  )

  // 선택된 프로젝트 인사이트
  const projectInsights = useMemo(() => {
    if (!selectedProjectId || !insights.data?.projects[selectedProjectId]) return []
    return insights.data.projects[selectedProjectId].items
  }, [selectedProjectId, insights.data])

  // 새 인사이트 생성
  const generateMutation = useMutation({
    mutationFn: generateInsights,
    onSuccess: () => {
      toast.success('인사이트 생성이 시작되었습니다. 잠시 후 화면을 새로고침해주세요.')
      // 3초 후 자동 새로고침
      setTimeout(
        () => {
          queryClient.invalidateQueries({ queryKey: queryKeys.insights.all })
        },
        3000,
      )
    },
    onError: (err) => {
      toast.error(`인사이트 생성 실패: ${(err as Error).message}`)
    },
  })

  if (insights.isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    )
  }

  if (insights.isError) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        인사이트 로드 실패: {(insights.error as Error).message}
      </div>
    )
  }

  const portfolioItems = insights.data?.portfolio ?? []
  const hasAnyInsights = portfolioItems.length > 0 || Object.keys(insights.data?.projects ?? {}).length > 0

  return (
    <div className="space-y-4">
      {/* 헤더 + 버튼 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">AI 인사이트</h2>
          <p className="text-sm text-muted-foreground">포트폴리오 및 프로젝트별 AI 분석</p>
        </div>
        <Button
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
          size="sm"
          className="gap-2"
        >
          <Sparkles className="h-4 w-4" />
          {generateMutation.isPending ? '생성 중...' : '새로 생성'}
        </Button>
      </div>

      {!hasAnyInsights ? (
        <div className="rounded-md border border-dashed border-muted-foreground p-8 text-center">
          <p className="text-sm text-muted-foreground">
            아직 생성된 인사이트가 없습니다. '새로 생성' 버튼을 눌러주세요.
          </p>
        </div>
      ) : (
        <Tabs defaultValue="portfolio" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="portfolio">포트폴리오 인사이트</TabsTrigger>
            <TabsTrigger value="projects">프로젝트별 인사이트</TabsTrigger>
          </TabsList>

          {/* 포트폴리오 탭 */}
          <TabsContent value="portfolio" className="space-y-3">
            {portfolioItems.length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {portfolioItems.map((insight, idx) => (
                  <InsightCard key={idx} insight={insight} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">포트폴리오 인사이트가 없습니다.</p>
            )}
          </TabsContent>

          {/* 프로젝트별 탭 */}
          <TabsContent value="projects" className="space-y-4">
            <ProjectSelect />

            {selectedProjectId ? (
              projectInsights.length > 0 ? (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {projectInsights.map((insight, idx) => (
                    <InsightCard key={idx} insight={insight} />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">이 프로젝트의 인사이트가 없습니다.</p>
              )
            ) : (
              <p className="text-sm text-muted-foreground">프로젝트를 선택하면 인사이트를 확인할 수 있습니다.</p>
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
