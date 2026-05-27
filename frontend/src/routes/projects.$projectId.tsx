import { createFileRoute } from '@tanstack/react-router'

import { ProjectDetailPage } from '@/features/projects/ProjectDetailPage'

export const Route = createFileRoute('/projects/$projectId')({
  component: RouteComponent,
})

function RouteComponent() {
  const { projectId } = Route.useParams()
  const id = Number(projectId)
  if (!Number.isFinite(id)) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        잘못된 프로젝트 ID: {projectId}
      </div>
    )
  }
  return <ProjectDetailPage projectId={id} />
}
