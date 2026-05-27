import { createFileRoute } from '@tanstack/react-router'

import { KanbanPage } from '@/features/kanban/KanbanPage'

export const Route = createFileRoute('/kanban')({
  component: KanbanPage,
})
