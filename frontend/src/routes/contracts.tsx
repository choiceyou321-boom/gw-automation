import { createFileRoute } from '@tanstack/react-router'

import { ContractsPage } from '@/features/pipeline/ContractsPage'

export const Route = createFileRoute('/contracts')({
  component: ContractsPage,
})
