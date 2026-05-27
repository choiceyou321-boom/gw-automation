import { Link, useRouterState } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/', label: '대시보드' },
  { to: '/overview', label: '개요' },
  { to: '/schedule', label: '일정표' },
  { to: '/kanban', label: '칸반' },
  { to: '/collections', label: '수금' },
  { to: '/payments', label: '이체' },
  { to: '/budget-payment', label: '예산집행' },
  { to: '/vendors', label: '하도급' },
  { to: '/contracts', label: '계약' },
  { to: '/risks', label: '리스크' },
  { to: '/inbox', label: '알림' },
  { to: '/insights', label: 'AI 인사이트' },
] as const

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <aside className="flex w-56 flex-col border-r bg-card">
        <div className="px-4 py-4 text-lg font-semibold tracking-tight">
          PM <span className="text-muted-foreground">v5</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-2 py-2">
          {NAV_ITEMS.map((item) => {
            const active =
              item.to === '/'
                ? pathname === '/'
                : pathname.startsWith(item.to)
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  'rounded-md px-3 py-2 text-sm transition-colors',
                  active
                    ? 'bg-accent text-accent-foreground font-medium'
                    : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                )}
              >
                {item.label}
              </Link>
            )
          })}
        </nav>
        <div className="px-4 py-3 text-xs text-muted-foreground">
          <a href="/fund" className="hover:underline">레거시(/fund) 열기 →</a>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto bg-background">
        <div className="p-6">{children}</div>
      </main>
    </div>
  )
}
