import { createFileRoute } from '@tanstack/react-router'
import { VendorsPage } from '@/features/vendors/VendorsPage'

export const Route = createFileRoute('/vendors')({
  component: VendorsPage,
})
