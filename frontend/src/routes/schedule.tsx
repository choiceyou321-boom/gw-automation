import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/schedule')({
  component: SchedulePage,
})

function SchedulePage() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">일정표</h1>
      <p className="mt-2 text-sm text-muted-foreground">v5.N에서 구현 예정 (스텁).</p>
    </div>
  )
}
