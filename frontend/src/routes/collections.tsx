import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/collections')({
  component: CollectionsPage,
})

function CollectionsPage() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">수금</h1>
      <p className="mt-2 text-sm text-muted-foreground">v5.N에서 구현 예정 (스텁).</p>
    </div>
  )
}
