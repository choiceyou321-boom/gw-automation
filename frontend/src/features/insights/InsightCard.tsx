// (useState 미사용 — v6.4에서 도입된 isDeleting 패턴 제거됨)
import { useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { toast } from 'sonner'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { MoreVertical, Star, Trash2, CheckSquare, Flag } from 'lucide-react'
import type { Insight } from './api'
import { queryKeys } from '@/lib/query-keys'

interface InsightCardProps {
  insight: Insight
  onRefresh?: () => void
}

/**
 * insight_type → 배지 색상 매핑
 */
const typeColorMap: Record<string, 'default' | 'secondary' | 'destructive' | 'outline' | 'warning'> = {
  strategy: 'default',
  warning: 'warning',
  opportunity: 'secondary',
  risk: 'destructive',
  recommendation: 'default',
  blind_spot: 'destructive',
}

/**
 * insight_type → 한글 라벨
 */
const typeLabel: Record<string, string> = {
  strategy: '전략',
  warning: '주의',
  opportunity: '기회',
  risk: '위험',
  recommendation: '추천',
  blind_spot: '⚠️ 놓친 것',
}

export function InsightCard({ insight, onRefresh }: InsightCardProps) {
  // const [isDeleting, setIsDeleting] = useState(false)
  const queryClient = useQueryClient()
  const variant = typeColorMap[insight.insight_type] ?? 'outline'
  const label = typeLabel[insight.insight_type] ?? insight.insight_type

  // 생성 시간 포맷팅 (ISO 8601 → 상대 시간)
  const generatedDate = new Date(insight.generated_at)
  const now = new Date()
  const diffMs = now.getTime() - generatedDate.getTime()
  const diffMins = Math.floor(diffMs / (1000 * 60))

  let timeStr = ''
  if (diffMins < 1) timeStr = '방금 전'
  else if (diffMins < 60) timeStr = `${diffMins}분 전`
  else if (diffMins < 1440) timeStr = `${Math.floor(diffMins / 60)}시간 전`
  else timeStr = `${Math.floor(diffMins / 1440)}일 전`

  // 액션 mutations
  const pinMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/pm/insights/${insight.id}/pin`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error('핀 변경 실패')
      return res.json()
    },
    onSuccess: () => {
      toast.success('핀이 변경되었습니다')
      onRefresh?.()
      queryClient.invalidateQueries({ queryKey: queryKeys.insights.all })
    },
    onError: () => toast.error('핀 변경 실패'),
  })

  const deleteMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/pm/insights/${insight.id}`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error('삭제 실패')
      return res.json()
    },
    onSuccess: () => {
      toast.success('인사이트가 삭제되었습니다')
      onRefresh?.()
      queryClient.invalidateQueries({ queryKey: queryKeys.insights.all })
    },
    onError: () => toast.error('삭제 실패'),
  })

  const toTodoMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/pm/insights/${insight.id}/to-todo`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error('TODO 생성 실패')
      return res.json()
    },
    onSuccess: (data) => {
      const count = data.created?.length ?? 0
      toast.success(`${count}개의 TODO가 생성되었습니다`)
    },
    onError: () => toast.error('TODO 생성 실패'),
  })

  const toMilestoneMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/pm/insights/${insight.id}/to-milestone`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error('마일스톤 생성 실패')
      return res.json()
    },
    onSuccess: (data) => {
      const count = data.created?.length ?? 0
      toast.success(`${count}개의 마일스톤이 생성되었습니다`)
    },
    onError: () => toast.error('마일스톤 생성 실패'),
  })

  const isPinned = insight.is_pinned ? true : false

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          {isPinned && <Star className="h-4 w-4 fill-yellow-400 text-yellow-400" />}
          <Badge variant={variant}>{label}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{timeStr}</span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuItem onClick={() => pinMutation.mutate()}>
                <Star className="mr-2 h-4 w-4" />
                {isPinned ? '핀 제거' : '핀하기'}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => toTodoMutation.mutate()}>
                <CheckSquare className="mr-2 h-4 w-4" />
                할일로 만들기
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => toMilestoneMutation.mutate()}>
                <Flag className="mr-2 h-4 w-4" />
                마일스톤으로 만들기
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  if (confirm('정말 삭제하시겠습니까?')) {
                    deleteMutation.mutate()
                  }
                }}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                삭제
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Markdown 렌더링 */}
      <div className="text-sm leading-relaxed">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // heading 스타일
            h1: ({ node, ...props }) => <h1 className="mb-2 text-base font-semibold" {...props} />,
            h2: ({ node, ...props }) => <h2 className="mb-2 text-sm font-semibold" {...props} />,
            h3: ({ node, ...props }) => <h3 className="mb-1 text-xs font-semibold" {...props} />,
            // list 스타일
            ul: ({ node, ...props }) => <ul className="ml-4 list-disc space-y-1" {...props} />,
            ol: ({ node, ...props }) => <ol className="ml-4 list-decimal space-y-1" {...props} />,
            li: ({ node, ...props }) => <li className="text-sm" {...props} />,
            // code 스타일
            code: ({ node, ...props }: any) => {
              const isInline = !props.className?.includes('language-')
              return isInline ? (
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs" {...props} />
              ) : (
                <code className="block overflow-x-auto rounded bg-muted p-2 font-mono text-xs" {...props} />
              )
            },
            // 기타
            p: ({ node, ...props }) => <p className="mb-2" {...props} />,
            a: ({ node, ...props }) => <a className="text-primary underline" {...props} />,
          }}
        >
          {insight.content}
        </ReactMarkdown>
      </div>
    </Card>
  )
}
