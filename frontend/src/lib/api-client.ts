/**
 * FastAPI(:51749) 통신 래퍼.
 * 개발: Vite proxy로 same-origin → 쿠키 자동 첨부
 * 운영: FastAPI가 /pm-v2 직접 서빙 → 동일 origin
 */

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `API ${status}`)
    this.status = status
    this.body = body
  }
}

type ApiOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  searchParams?: Record<string, string | number | boolean | undefined>
}

async function request<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { body, searchParams, headers, ...rest } = options

  let finalPath = path
  if (searchParams) {
    const sp = new URLSearchParams()
    for (const [k, v] of Object.entries(searchParams)) {
      if (v !== undefined) sp.set(k, String(v))
    }
    const qs = sp.toString()
    if (qs) finalPath += (path.includes('?') ? '&' : '?') + qs
  }

  const init: RequestInit = {
    ...rest,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }

  const res = await fetch(finalPath, init)

  // 401 → 로그인 페이지로 (백엔드 vanilla)
  if (res.status === 401 && typeof window !== 'undefined') {
    window.location.href = `/login?next=${encodeURIComponent(window.location.href)}`
    throw new ApiError(401, null, 'Unauthorized')
  }

  if (!res.ok) {
    let errBody: unknown = null
    try {
      errBody = await res.json()
    } catch {
      errBody = await res.text()
    }
    throw new ApiError(res.status, errBody)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string, options?: Omit<ApiOptions, 'body' | 'method'>) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: Omit<ApiOptions, 'body' | 'method'>) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: Omit<ApiOptions, 'body' | 'method'>) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<ApiOptions, 'body' | 'method'>) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: Omit<ApiOptions, 'body' | 'method'>) =>
    request<T>(path, { ...options, method: 'DELETE' }),
}
