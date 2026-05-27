/** 금액 포맷 — 백엔드 fund.js의 1억/천만/만원 표기와 동일 룩 */
export function formatKRW(n: number | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return '-'
  const abs = Math.abs(n)
  if (abs >= 100_000_000) return `${(n / 100_000_000).toFixed(2)}억`
  if (abs >= 10_000_000) return `${(n / 10_000_000).toFixed(1)}천만`
  if (abs >= 10_000) return `${(n / 10_000).toFixed(0)}만`
  return n.toLocaleString('ko-KR')
}

export function formatPercent(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || isNaN(n)) return '-'
  return `${n.toFixed(digits)}%`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString('ko-KR', { year: '2-digit', month: '2-digit', day: '2-digit' })
}
