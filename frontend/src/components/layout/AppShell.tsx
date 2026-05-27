import { Link, useRouterState } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import {
  LayoutDashboard,
  Table2,
  CalendarDays,
  KanbanSquare,
  Wallet,
  BanknoteArrowDown,
  ScrollText,
  Receipt,
  Users,
  AlertTriangle,
  Inbox,
  Sparkles,
} from 'lucide-react'

import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/', label: '대시보드', Icon: LayoutDashboard },
  { to: '/overview', label: '개요', Icon: Table2 },
  { to: '/schedule', label: '일정표', Icon: CalendarDays },
  { to: '/kanban', label: '칸반', Icon: KanbanSquare },
  { to: '/collections', label: '수금', Icon: BanknoteArrowDown },
  { to: '/payments', label: '이체', Icon: Receipt },
  { to: '/budget-payment', label: '예산집행', Icon: Wallet },
  { to: '/vendors', label: '하도급', Icon: Users },
  { to: '/contracts', label: '계약', Icon: ScrollText },
  { to: '/risks', label: '리스크', Icon: AlertTriangle },
  { to: '/inbox', label: '알림', Icon: Inbox },
  { to: '/insights', label: 'AI 인사이트', Icon: Sparkles },
] as const

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <aside className="flex w-56 flex-col border-r border-stone-200 bg-card">
        <div className="flex items-center gap-2 px-4 py-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-900 text-white text-xs font-semibold">
            PM
          </div>
          <span className="text-sm font-medium tracking-tight text-stone-900">
            프로젝트 관리
          </span>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5 px-2 py-1">
          {NAV_ITEMS.map((item) => {
            const active =
              item.to === '/'
                ? pathname === '/'
                : pathname.startsWith(item.to)
            const Icon = item.Icon
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  'group flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors',
                  active
                    ? 'bg-stone-100 text-stone-900 font-medium'
                    : 'text-stone-600 hover:bg-stone-50 hover:text-stone-900',
                )}
              >
                <Icon
                  size={16}
                  className={cn(
                    'shrink-0',
                    active ? 'text-stone-900' : 'text-stone-400 group-hover:text-stone-600',
                  )}
                />
                {item.label}
              </Link>
            )
          })}
        </nav>
      </aside>
      <main className="flex-1 overflow-y-auto bg-background">
        <div className="p-6">{children}</div>
      </main>
    </div>
  )
}
