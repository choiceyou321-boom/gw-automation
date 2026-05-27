import { clsx } from 'clsx'
import type { ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** shadcn 표준 — Tailwind 클래스 조합 + 충돌 해결 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
