import { createRootRouteWithContext, Outlet, redirect } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/router-devtools'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import type { QueryClient } from '@tanstack/react-query'

import { AppShell } from '@/components/layout/AppShell'
import { queryKeys } from '@/lib/query-keys'
import { fetchMe } from '@/features/auth/api'
import type { Me } from '@/features/auth/api'

interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  beforeLoad: async ({ context, location }) => {
    // /login 같은 비보호 경로면 통과 (v5.1에서는 일단 전부 보호)
    try {
      const me = await context.queryClient.ensureQueryData<Me>({
        queryKey: queryKeys.auth.me,
        queryFn: fetchMe,
        staleTime: 5 * 60 * 1000,
      })
      return { me }
    } catch {
      // 미인증 → 기존 vanilla 로그인 페이지로 리다이렉트
      // (v5는 자체 로그인 UI 없음, 백엔드 /login 재사용)
      if (typeof window !== 'undefined') {
        window.location.href = `/login?next=${encodeURIComponent(location.href)}`
      }
      throw redirect({ to: '/' })
    }
  },
  component: RootComponent,
})

function RootComponent() {
  return (
    <AppShell>
      <Outlet />
      {import.meta.env.DEV && (
        <>
          <TanStackRouterDevtools position="bottom-right" />
          <ReactQueryDevtools buttonPosition="bottom-left" />
        </>
      )}
    </AppShell>
  )
}
