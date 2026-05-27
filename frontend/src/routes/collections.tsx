import { createFileRoute } from '@tanstack/react-router'

import { CollectionsPage } from '@/features/pipeline/CollectionsPage'

export const Route = createFileRoute('/collections')({
  component: CollectionsPage,
})
