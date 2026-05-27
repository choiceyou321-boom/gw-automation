import { createFileRoute } from '@tanstack/react-router'

import { SchedulePage } from '@/features/schedule/SchedulePage'

export const Route = createFileRoute('/schedule')({
  component: SchedulePage,
})
