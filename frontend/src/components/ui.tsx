/**
 * Shared presentational pieces.
 *
 * Kept deliberately small: a card, a table, a badge, a few form fields and the
 * empty/error/loading states every screen needs. The one piece with real logic
 * is `Paginator`, which reads `meta` rather than tracking page state itself.
 */

import type { ReactNode } from 'react'

import { ApiError } from '../lib/api'
import { useI18n } from '../lib/i18n'
import type { PaginationMeta } from '../lib/types'

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

// --- layout ----------------------------------------------------------------

export function Card({
  title,
  subtitle,
  action,
  children,
  className,
  padded = true,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <section className={cx('rounded-xl border border-stone-200 bg-white shadow-sm', className)}>
      {(title || action) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-stone-200 px-4 py-3">
          <div>
            {title && <h2 className="text-base font-semibold text-stone-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-stone-500">{subtitle}</p>}
          </div>
          {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={padded ? 'p-4' : ''}>{children}</div>
    </section>
  )
}

/** Responsive grid used by every stat row. Tiles come from dashboardParts. */
export function StatGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>
  )
}

// --- states ----------------------------------------------------------------

export function Loading({ label }: { label?: string }) {
  const { t } = useI18n()
  return (
    <div className="flex items-center justify-center gap-3 py-12 text-stone-500" role="status">
      <span
        className="size-5 animate-spin rounded-full border-2 border-stone-300 border-t-emerald-600"
        aria-hidden
      />
      <span className="text-sm">{label ?? t('app.loading')}</span>
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title?: string
  hint?: string
  action?: ReactNode
}) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <p className="text-sm font-medium text-stone-700">{title ?? t('app.noResults')}</p>
      {hint && <p className="max-w-sm text-sm text-stone-500">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/**
 * Turns any thrown value into something worth showing. ApiError already carries
 * the backend's own message, which is already user-facing, so it is preferred
 * over a generic string. The request id is shown because it is the one thing a
 * user can quote when reporting a problem.
 */
export function ErrorState({
  error,
  onRetry,
  compact = false,
}: {
  error: unknown
  onRetry?: () => void
  /** Denser padding for errors raised inside a form next to its submit button. */
  compact?: boolean
}) {
  const { t } = useI18n()
  if (!error) return null
  const api = error instanceof ApiError ? error : null
  const message = api?.message ?? (error instanceof Error ? error.message : t('app.errorHint'))
  const title = api?.status === 403 ? null : t('app.error')

  return (
    <div
      className={cx(
        'rounded-lg border border-red-200 bg-red-50 text-sm text-red-900',
        compact ? 'p-3' : 'p-4',
      )}
      role="alert"
    >
      {title && <p className="font-semibold">{title}</p>}
      <p>{message}</p>
      {api?.fieldErrors && Object.keys(api.fieldErrors).length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5">
          {Object.entries(api.fieldErrors).map(([field, messages]) => (
            <li key={field}>
              <span className="font-medium">{field}:</span> {messages.join(', ')}
            </li>
          ))}
        </ul>
      )}
      {api?.requestId && (
        <p className="mt-2 text-xs text-red-700/80">
          Request id: <code>{api.requestId}</code>
        </p>
      )}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-800 hover:bg-red-100"
        >
          {t('app.retry')}
        </button>
      )}
    </div>
  )
}

// --- badges ----------------------------------------------------------------

const TONES = {
  neutral: 'bg-stone-100 text-stone-700 ring-stone-200',
  info: 'bg-sky-50 text-sky-800 ring-sky-200',
  success: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
  warning: 'bg-amber-50 text-amber-900 ring-amber-200',
  danger: 'bg-red-50 text-red-800 ring-red-200',
  purple: 'bg-violet-50 text-violet-800 ring-violet-200',
} as const

export type Tone = keyof typeof TONES

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        TONES[tone],
      )}
    >
      {children}
    </span>
  )
}

/** Maps an order status to a tone once, so all screens colour them alike. */
export function orderTone(status: string): Tone {
  switch (status) {
    case 'COMPLETED':
    case 'PAYMENT_COMPLETED':
    case 'QUALITY_CONFIRMED':
    case 'DELIVERED':
      return 'success'
    case 'CANCELLED':
      return 'danger'
    case 'PICKUP_SCHEDULED':
    case 'IN_TRANSIT':
    case 'LOGISTICS_ASSIGNED':
      return 'info'
    case 'PAYMENT_PENDING':
    case 'OFFER_ACCEPTED':
    case 'ORDER_CREATED':
      return 'warning'
    default:
      return 'neutral'
  }
}

export function offerTone(status: string): Tone {
  switch (status) {
    case 'ACCEPTED':
      return 'success'
    case 'REJECTED':
    case 'EXPIRED':
      return 'danger'
    case 'COUNTERED':
      return 'purple'
    case 'PENDING':
      return 'warning'
    default:
      return 'neutral'
  }
}

export function lotTone(status: string): Tone {
  switch (status) {
    case 'PUBLISHED':
      return 'success'
    case 'UNDER_OFFER':
      return 'warning'
    case 'SOLD':
    case 'IN_TRANSIT':
    case 'COMPLETED':
      return 'info'
    case 'CANCELLED':
      return 'danger'
    default:
      return 'neutral'
  }
}

export function demandTone(status: string): Tone {
  switch (status) {
    case 'OPEN':
      return 'success'
    case 'PARTIALLY_FULFILLED':
      return 'warning'
    case 'FULFILLED':
    case 'CLOSED':
      return 'neutral'
    case 'EXPIRED':
      return 'danger'
    default:
      return 'neutral'
  }
}

export function paymentTone(status: string | null): Tone {
  switch (status) {
    case 'PAID':
      return 'success'
    case 'FAILED':
    case 'DISPUTED':
      return 'danger'
    case 'PROCESSING':
      return 'info'
    default:
      return 'warning'
  }
}

// --- table -----------------------------------------------------------------

/**
 * Wraps the table markup every list needs: a horizontally scrollable region so
 * wide tables do not break the phone layout, and a caption slot for the column
 * headers' meaning. `columns` drives the header row, keeping head and body
 * aligned without a table library.
 */
export function Table({
  caption,
  columns,
  children,
}: {
  caption?: string
  columns: string[]
  children: ReactNode
}) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-max border-collapse text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-stone-200">
            {columns.map((column) => (
              <th
                key={column}
                scope="col"
                className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-stone-500 uppercase whitespace-nowrap"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100">{children}</tbody>
      </table>
    </div>
  )
}

export function Paginator({
  meta,
  onPage,
}: {
  meta: PaginationMeta | null
  onPage: (page: number) => void
}) {
  const { t } = useI18n()
  if (!meta || meta.total_pages <= 1) return null
  return (
    <nav
      className="mt-4 flex items-center justify-between gap-3 text-sm"
      aria-label={t('nav.menu')}
    >
      <p className="text-stone-500">
        {meta.total_items} {t('app.of')} {meta.total_pages}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!meta.has_previous}
          onClick={() => onPage(meta.page - 1)}
          className="rounded-md border border-stone-300 px-3 py-1.5 disabled:opacity-40"
        >
          {t('app.previous')}
        </button>
        <span className="self-center text-stone-600">
          {meta.page} / {meta.total_pages}
        </span>
        <button
          type="button"
          disabled={!meta.has_next}
          onClick={() => onPage(meta.page + 1)}
          className="rounded-md border border-stone-300 px-3 py-1.5 disabled:opacity-40"
        >
          {t('app.next')}
        </button>
      </div>
    </nav>
  )
}
