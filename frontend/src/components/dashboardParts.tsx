/**
 * Pieces the three dashboards share.
 *
 * Keeping them here rather than inlining them is what makes the demo-data
 * warning consistent: there is exactly one `DemoBanner` in the codebase, so
 * every screen that shows synthetic prices warns the same way.
 */

import { useI18n } from '../lib/i18n'
import { Card, cx } from './ui'
import { StatusBadge, UnitLabel } from './labels'
import type { MarketInsightCard, PipelineBucket, PriceCard } from '../lib/types'

/**
 * The demo warning. Rendered above dashboard content, never dismissible, and
 * always paired with the price cards it applies to.
 */
export function DemoBanner() {
  const { t } = useI18n()
  return (
    <div
      className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
      role="note"
    >
      <span aria-hidden className="text-base leading-none">
        ⚠️
      </span>
      <div>
        <p className="font-medium">{t('app.demoBanner')}</p>
        <p className="mt-0.5 text-xs text-amber-800">{t('market.demoNotice')}</p>
      </div>
    </div>
  )
}

export function StatTile({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string
  value: string
  hint?: string | null
  tone?: 'default' | 'positive' | 'negative' | 'warning'
}) {
  const toneClass = {
    default: 'text-stone-900',
    positive: 'text-emerald-700',
    negative: 'text-red-700',
    warning: 'text-amber-700',
  }[tone]
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-4">
      <p className="text-xs font-medium tracking-wide text-stone-500 uppercase">{label}</p>
      <p className={cx('mt-1 text-2xl font-semibold', toneClass)}>{value}</p>
      {hint && <p className="mt-1 text-xs text-stone-500">{hint}</p>}
    </div>
  )
}

const TREND_ARROW = { up: '▲', down: '▼', flat: '■' } as const

export function PriceCardRow({ cards }: { cards: PriceCard[] }) {
  const { t, money, number, date } = useI18n()
  if (cards.length === 0) return null

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {cards.map((card) => {
        const arrow = TREND_ARROW[card.trend] ?? '■'
        const changeTone =
          card.trend === 'up' ? 'text-emerald-700' : card.trend === 'down' ? 'text-red-700' : 'text-stone-500'
        return (
          <div key={card.commodity_id} className="rounded-lg border border-stone-200 p-3">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-stone-900">{card.commodity_name}</p>
              {card.change_pct_7d !== null && (
                <span className={cx('text-xs font-medium whitespace-nowrap', changeTone)}>
                  <span aria-hidden>{arrow}</span>{' '}
                  {card.change_pct_7d > 0 ? '+' : ''}
                  {number(card.change_pct_7d)}%
                </span>
              )}
            </div>
            <p className="mt-1.5 text-xl font-semibold text-stone-900">
              {card.modal_price !== null ? money(card.modal_price) : '—'}
              <span className="ml-1 text-sm font-normal text-stone-500">
                / <UnitLabel unit={card.unit} />
              </span>
            </p>
            <p className="mt-1 text-xs text-stone-500">
              {t('market.min')}: {money(card.min_price)} · {t('market.highest')}:{' '}
              {money(card.max_price)}
            </p>
            <p className="mt-0.5 text-xs text-stone-400">
              {card.price_date
                ? date(card.price_date)
                : t('market.medianAcross', { count: number(card.market_count ?? 0) })}
              {card.arrivals_quintal !== null &&
                ` · ${t('market.arrivals')}: ${number(card.arrivals_quintal)}`}
            </p>
            {card.my_lots > 0 && (
              <p className="mt-1.5 text-xs text-emerald-700">
                {t('dash.seller.lots')}: {number(card.my_lots)}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}

const TONE_FOR_INSIGHT: Record<string, string> = {
  positive: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
  negative: 'border-red-200 bg-red-50 text-red-900',
  info: 'border-sky-200 bg-sky-50 text-sky-900',
}

/**
 * Suggestions carry a `tone` from the backend. They are advisory only, so each
 * one is labelled as advice rather than fact and none are presented as a
 * guarantee of price.
 */
export function InsightList({ insights }: { insights: MarketInsightCard[] }) {
  const { t } = useI18n()
  if (insights.length === 0) return null
  return (
    <ul className="space-y-2">
      {insights.map((insight, index) => (
        <li
          key={`${insight.kind}-${index}`}
          className={cx(
            'rounded-lg border p-3 text-sm',
            TONE_FOR_INSIGHT[insight.tone ?? 'info'] ?? TONE_FOR_INSIGHT.info,
          )}
        >
          <p className="font-medium">{insight.title}</p>
          <p className="mt-0.5 text-sm opacity-90">{insight.message}</p>
          {insight.confidence && (
            <p className="mt-1 text-xs opacity-70">
              {t('match.score')}: {insight.confidence}
            </p>
          )}
        </li>
      ))}
    </ul>
  )
}

/**
 * Order pipeline as a proportional bar. A buyer or farmer with no orders still
 * sees the full lifecycle, so the shape of a trade is visible before one starts.
 */
export function PipelineBar({ buckets }: { buckets: PipelineBucket[] }) {
  const { t, moneyCompact, number } = useI18n()
  if (!buckets || buckets.length === 0) return null

  const total = buckets.reduce((sum, b) => sum + b.count, 0)
  const nonZero = buckets.filter((bucket) => bucket.count > 0)

  if (total === 0) {
    return (
      <p className="py-6 text-center text-sm text-stone-500">
        {t('order.noOrders')}
        <span className="mt-1 block text-xs text-stone-400">{t('order.noOrdersHint')}</span>
      </p>
    )
  }

  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full bg-stone-200">
        {nonZero.map((bucket) => (
          <div
            key={bucket.status}
            className="bg-emerald-600 first:rounded-l-full last:rounded-r-full"
            style={{ width: `${(bucket.count / total) * 100}%` }}
            title={`${bucket.status}: ${bucket.count}`}
          />
        ))}
      </div>
      <ul className="mt-3 space-y-1.5">
        {nonZero.map((bucket) => (
          <li key={bucket.status} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-stone-700">
              <StatusBadge
                value={bucket.status}
                tone={bucket.status === 'CANCELLED' ? 'danger' : 'info'}
                domain="order"
              />
              <span className="text-xs text-stone-500">{number(bucket.count)}</span>
            </span>
            <span className="text-stone-600">{moneyCompact(bucket.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Card wrapper for a section of a dashboard that has no dedicated component. */
export function DashboardCard(props: React.ComponentProps<typeof Card>) {
  return <Card {...props} />
}
