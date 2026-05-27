import { createFileRoute } from '@tanstack/react-router'

import { OverviewPage } from '@/features/projects/OverviewPage'

export const Route = createFileRoute('/overview')({
  component: OverviewPage,
})
