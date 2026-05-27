import { createFileRoute } from '@tanstack/react-router'
import { BudgetPaymentPage } from '@/features/budget/BudgetPaymentPage'

export const Route = createFileRoute('/budget-payment')({
  component: BudgetPaymentPage,
})
