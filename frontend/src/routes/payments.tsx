import { createFileRoute } from '@tanstack/react-router'

import { PaymentsPage } from '@/features/pipeline/PaymentsPage'

export const Route = createFileRoute('/payments')({
  component: PaymentsPage,
})
