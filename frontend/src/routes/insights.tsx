import { createFileRoute } from '@tanstack/react-router'
import { InsightsPanel } from '@/features/insights/InsightsPanel'

export const Route = createFileRoute('/insights')({
  component: InsightsRoute,
})

function InsightsRoute() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">AI 인사이트</h1>
        <p className="mt-1 text-sm text-muted-foreground">포트폴리오 및 프로젝트별 AI 분석 결과</p>
      </header>

      <InsightsPanel />
    </div>
  )
}
