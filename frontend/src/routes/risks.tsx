import { createFileRoute } from '@tanstack/react-router'
import { RisksPage } from '@/features/risks/RisksPage'

export const Route = createFileRoute('/risks')({
  component: RisksPage,
})
