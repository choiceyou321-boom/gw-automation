import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { Insight } from './api'

interface InsightCardProps {
  insight: Insight
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
}

export function InsightCard({ insight }: InsightCardProps) {
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

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <Badge variant={variant}>{label}</Badge>
        <span className="text-xs text-muted-foreground">{timeStr}</span>
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
