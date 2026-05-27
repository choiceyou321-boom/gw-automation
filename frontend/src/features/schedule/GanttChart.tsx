import { useMemo, useState } from 'react'
import type { ScheduleItem } from './api'
import { cn } from '@/lib/utils'

const DAY_MS = 24 * 60 * 60 * 1000

const STATUS_COLOR: Record<string, string> = {
  planned: 'fill-slate-400',
  in_progress: 'fill-blue-500',
  done: 'fill-emerald-500',
  blocked: 'fill-amber-500',
  critical: 'fill-red-500',
}

function parseDate(s: string): Date | null {
  if (!s) return null
  const d = new Date(s)
  return isNaN(d.getTime()) ? null : d
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

function diffDays(a: Date, b: Date): number {
  return Math.round((startOfDay(b).getTime() - startOfDay(a).getTime()) / DAY_MS)
}

function fmt(d: Date): string {
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
}

interface GanttChartProps {
  items: ScheduleItem[]
  rowHeight?: number
  /** 우측 막대 영역 가로 픽셀 너비 (스크롤) */
  width?: number
}

export function GanttChart({ items, rowHeight = 32, width = 1200 }: GanttChartProps) {
  const [hover, setHover] = useState<ScheduleItem | null>(null)

  const { range, days } = useMemo(() => {
    const dates: Date[] = []
    for (const it of items) {
      const s = parseDate(it.start_date)
      const e = parseDate(it.end_date)
      if (s) dates.push(s)
      if (e) dates.push(e)
    }
    if (dates.length === 0) {
      const now = new Date()
      const start = new Date(now.getFullYear(), now.getMonth() - 1, 1)
      const end = new Date(now.getFullYear(), now.getMonth() + 2, 0)
      return { range: { start, end }, days: diffDays(start, end) + 1 }
    }
    const min = new Date(Math.min(...dates.map((d) => d.getTime())))
    const max = new Date(Math.max(...dates.map((d) => d.getTime())))
    const start = startOfDay(min)
    const end = startOfDay(max)
    return { range: { start, end }, days: Math.max(diffDays(start, end) + 1, 30) }
  }, [items])

  const pxPerDay = Math.max(width / days, 4)
  const labelWidth = 240
  const totalWidth = labelWidth + days * pxPerDay
  const headerHeight = 32
  const height = headerHeight + items.length * rowHeight + 8

  // 월 경계 마커
  const monthMarkers = useMemo(() => {
    const out: { x: number; label: string }[] = []
    const cursor = new Date(range.start)
    while (cursor <= range.end) {
      const dx = diffDays(range.start, cursor) * pxPerDay
      out.push({
        x: dx,
        label: `${cursor.getFullYear()}.${String(cursor.getMonth() + 1).padStart(2, '0')}`,
      })
      cursor.setMonth(cursor.getMonth() + 1)
      cursor.setDate(1)
    }
    return out
  }, [range, pxPerDay])

  if (items.length === 0) {
    return (
      <div className="rounded-md border bg-card p-8 text-center text-sm text-muted-foreground">
        등록된 일정 항목이 없습니다.
      </div>
    )
  }

  return (
    <div className="relative overflow-x-auto rounded-md border bg-card">
      <svg width={totalWidth} height={height} className="block">
        {/* 라벨 영역 배경 */}
        <rect x={0} y={0} width={labelWidth} height={height} className="fill-muted/30" />

        {/* 헤더 — 월 경계 */}
        <g transform={`translate(${labelWidth}, 0)`}>
          {monthMarkers.map((m, i) => (
            <g key={i}>
              <line
                x1={m.x}
                y1={0}
                x2={m.x}
                y2={height}
                className="stroke-border"
                strokeDasharray="2,2"
              />
              <text x={m.x + 4} y={20} className="fill-muted-foreground text-[11px]">
                {m.label}
              </text>
            </g>
          ))}
        </g>

        {/* 행 + 막대 */}
        {items.map((it, idx) => {
          const y = headerHeight + idx * rowHeight
          const s = parseDate(it.start_date)
          const e = parseDate(it.end_date)
          if (!s || !e) {
            return (
              <g key={it.id}>
                <text
                  x={8}
                  y={y + rowHeight / 2 + 4}
                  className="fill-foreground text-xs"
                >
                  {it.item_name}
                </text>
                <text
                  x={labelWidth + 8}
                  y={y + rowHeight / 2 + 4}
                  className="fill-muted-foreground text-[11px]"
                >
                  날짜 미지정
                </text>
              </g>
            )
          }
          const x = labelWidth + diffDays(range.start, s) * pxPerDay
          const w = Math.max((diffDays(s, e) + 1) * pxPerDay, 4)
          const colorCls = STATUS_COLOR[it.status] ?? STATUS_COLOR.planned
          return (
            <g key={it.id}>
              {idx % 2 === 1 && (
                <rect
                  x={0}
                  y={y}
                  width={totalWidth}
                  height={rowHeight}
                  className="fill-muted/10"
                />
              )}
              <text
                x={8}
                y={y + rowHeight / 2 + 4}
                className="fill-foreground text-xs"
              >
                {it.item_name.length > 22 ? it.item_name.slice(0, 22) + '…' : it.item_name}
              </text>
              <rect
                x={x}
                y={y + 6}
                width={w}
                height={rowHeight - 12}
                rx={3}
                ry={3}
                className={cn(colorCls, 'cursor-pointer transition-opacity', hover?.id === it.id ? 'opacity-100' : 'opacity-90')}
                onMouseEnter={() => setHover(it)}
                onMouseLeave={() => setHover(null)}
              />
              {it.status === 'critical' && (
                <rect
                  x={x}
                  y={y + 6}
                  width={w}
                  height={rowHeight - 12}
                  rx={3}
                  ry={3}
                  fill="none"
                  className="stroke-red-700"
                  strokeWidth={2}
                />
              )}
            </g>
          )
        })}
      </svg>
      {hover && (
        <div className="pointer-events-none absolute right-4 top-4 rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
          <div className="font-medium">{hover.item_name}</div>
          <div className="mt-1 text-muted-foreground">
            {fmt(parseDate(hover.start_date)!)} ~ {fmt(parseDate(hover.end_date)!)}
          </div>
          <div className="mt-1 text-muted-foreground">상태: {hover.status}</div>
          {hover.notes && <div className="mt-1 text-muted-foreground">{hover.notes}</div>}
        </div>
      )}
    </div>
  )
}
