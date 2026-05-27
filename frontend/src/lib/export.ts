/**
 * 공용 익스포트 유틸 — CSV / Excel(.xlsx) / Markdown
 * 무거운 xlsx 라이브러리는 동적 import로 lazy load (사용 시점에만 번들 로드)
 */

export interface ExportColumn<T> {
  key: keyof T | string
  label: string
  format?: (row: T) => string | number | boolean | null | undefined
}

function escapeCsvCell(v: unknown): string {
  if (v === null || v === undefined) return ''
  const s = String(v)
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

function cellValue<T>(row: T, col: ExportColumn<T>): string {
  const raw =
    col.format !== undefined
      ? col.format(row)
      : (row as Record<string, unknown>)[col.key as string]
  if (raw === null || raw === undefined) return ''
  return String(raw)
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** CSV 익스포트 — 자체 구현 (라이브러리 없음). Excel 호환 BOM 포함. */
export function exportCsv<T>(
  rows: T[],
  columns: ExportColumn<T>[],
  filename: string,
): void {
  const header = columns.map((c) => escapeCsvCell(c.label)).join(',')
  const body = rows
    .map((row) => columns.map((col) => escapeCsvCell(cellValue(row, col))).join(','))
    .join('\n')
  const csv = '﻿' + header + '\n' + body + '\n' // UTF-8 BOM (Excel 한글 깨짐 방지)
  downloadBlob(new Blob([csv], { type: 'text/csv;charset=utf-8' }), filename)
}

/** Excel .xlsx 익스포트 — SheetJS 동적 import (≈800KB lazy) */
export async function exportExcel<T>(
  rows: T[],
  columns: ExportColumn<T>[],
  filename: string,
  sheetName = 'Sheet1',
): Promise<void> {
  const XLSX = await import('xlsx')
  const data = [
    columns.map((c) => c.label),
    ...rows.map((row) => columns.map((col) => cellValue(row, col))),
  ]
  const ws = XLSX.utils.aoa_to_sheet(data)
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, sheetName)
  XLSX.writeFile(wb, filename)
}

/** Markdown 테이블 — 보고서 작성용 */
export function exportMarkdown<T>(
  rows: T[],
  columns: ExportColumn<T>[],
  filename: string,
  title?: string,
): void {
  const lines: string[] = []
  if (title) {
    lines.push(`# ${title}`)
    lines.push('')
    lines.push(`> 생성 ${new Date().toLocaleString('ko-KR')} · ${rows.length}건`)
    lines.push('')
  }
  lines.push('| ' + columns.map((c) => c.label).join(' | ') + ' |')
  lines.push('| ' + columns.map(() => '---').join(' | ') + ' |')
  for (const row of rows) {
    lines.push(
      '| ' +
        columns
          .map((col) => {
            const v = cellValue(row, col).replace(/\|/g, '\\|').replace(/\n/g, ' ')
            return v
          })
          .join(' | ') +
        ' |',
    )
  }
  const md = lines.join('\n') + '\n'
  downloadBlob(new Blob([md], { type: 'text/markdown;charset=utf-8' }), filename)
}

export type ExportFormat = 'csv' | 'xlsx' | 'md'

/** 통합 호출 — 포맷에 따라 적절한 함수로 라우팅 */
export async function exportData<T>(
  format: ExportFormat,
  rows: T[],
  columns: ExportColumn<T>[],
  filenameBase: string,
  title?: string,
): Promise<void> {
  switch (format) {
    case 'csv':
      return exportCsv(rows, columns, `${filenameBase}.csv`)
    case 'xlsx':
      return exportExcel(rows, columns, `${filenameBase}.xlsx`)
    case 'md':
      return exportMarkdown(rows, columns, `${filenameBase}.md`, title)
  }
}
