import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: DashboardPage,
})

function DashboardPage() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">대시보드</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        v5.1 셋업 완료. v5.2에서 포트폴리오 KPI + 53건 카드를 채울 예정.
      </p>
    </div>
  )
}
