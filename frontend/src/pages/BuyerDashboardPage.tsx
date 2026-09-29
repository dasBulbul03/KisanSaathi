/**
 * Buyer dashboard.
 *
 * An unverified buyer sees a persistent verification notice near the top.
 * That is deliberate: the backend lets unverified buyers create demands and send
 * offers, but sellers see their badge and often price accordingly, so a buyer
 * who does not know they are unverified is being quietly disadvantaged.
 */

import { useNavigate } from 'react-router-dom'

import { useAsync } from '../hooks'
import { dashboards, markets } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  StatGrid,
  Table,
  demandTone,
  orderTone,
  paymentTone,
} from '../components/ui'
import { Button } from '../components/form'
import { StatusBadge, UnitLabel } from '../components/labels'
import { DemoBanner, PipelineBar, PriceCardRow, StatTile } from '../components/dashboardParts'
import type { BuyerDashboard, CommodityOverviewRow, PriceCard } from '../lib/types'

export default function BuyerDashboardPage() {
  const { t, number, money } = useI18n()
  const navigate = useNavigate()

  const state = useAsync<BuyerDashboard>(async () => dashboards.buyer())
  // Rate context for a buyer. The dashboard does not carry price cards, so this
  // asks the endpoint that answers exactly this question.
  const rates = useAsync<CommodityOverviewRow[]>(
    async () => markets.overview(4),
    { enabled: Boolean(state.data) },
  )

  if (state.initialLoading) return <Loading />
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />
  const data = state.data
  if (!data) return null

  const verified = data.buyer.verification_status === 'VERIFIED'
  const priceCards = (rates.data ?? []).map(overviewToCard)

  return (
    <div className="space-y-5">
      {data.is_demo_data && <DemoBanner />}

      <header>
        <h1 className="text-xl font-semibold text-stone-900">
          {t('dash.greeting.buyer', { name: data.buyer.full_name.split(' ')[0] })}
        </h1>
        <p className="text-sm text-stone-500">
          {data.buyer.organisation_name ?? ''}
          {data.buyer.district ? ` · ${data.buyer.district}` : ''}
        </p>
      </header>

      {!verified && (
        <div
          className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
          role="status"
        >
          <span aria-hidden className="text-base leading-none">
            ⓘ
          </span>
          <div>
            <p className="font-medium">{t('dash.buyer.verify')}</p>
            <p className="mt-0.5 text-xs text-amber-800">{t('dash.buyer.verifyHint')}</p>
          </div>
        </div>
      )}

      <StatGrid>
        {data.stats.map((stat) => (
          <StatTile
            key={stat.label}
            label={stat.label}
            value={stat.display || number(stat.value)}
            hint={stat.hint}
            tone={
              stat.change_pct != null && stat.change_pct < 0
                ? 'negative'
                : stat.change_pct != null && stat.change_pct > 0
                  ? 'positive'
                  : 'default'
            }
          />
        ))}
      </StatGrid>

      <Card
        title={t('dash.priceToday')}
        action={
          <Button variant="secondary" size="sm" onClick={() => navigate('/market')}>
            {t('market.title')}
          </Button>
        }
      >
        {rates.error ? (
          <ErrorState error={rates.error} onRetry={rates.reload} compact />
        ) : priceCards.length === 0 && !rates.loading ? (
          <EmptyState title={t('app.noResults')} />
        ) : (
          <PriceCardRow cards={priceCards} />
        )}
      </Card>

      {data.recommended_lots.length > 0 && (
        <Card
          title={t('dash.recommended')}
          action={
            <Button variant="ghost" size="sm" onClick={() => navigate('/lots')}>
              {t('app.viewAll')}
            </Button>
          }
          padded={false}
        >
          <Table
            caption={t('dash.recommended')}
            columns={[
              t('lot.title'),
              t('offer.price'),
              t('match.score'),
              t('lot.distance'),
              '',
            ]}
          >
            {data.recommended_lots.map((match) => (
              <tr key={`${match.entity_type}-${match.entity_id}`} className="hover:bg-stone-50">
                <td className="px-3 py-2">
                  <p className="font-medium text-stone-900">{match.title ?? '—'}</p>
                  <p className="text-xs text-stone-500">
                    {match.commodity}
                    {match.seller_name ? ` · ${match.seller_name}` : ''}
                    {match.seller_organisation ? ` (${match.seller_organisation})` : ''}
                  </p>
                  {match.reasons.length > 0 && (
                    <p className="mt-1 text-xs text-emerald-700">
                      {t('match.why')}: {match.reasons.join(', ')}
                    </p>
                  )}
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  {match.expected_price ? money(match.expected_price) : '—'}
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  <span className="text-sm font-medium text-stone-700">
                    {number(match.score)}
                  </span>
                  <span className="ml-1 text-xs text-stone-500">
                    {t(`match.${match.score_label.toLowerCase()}` as never)}
                  </span>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                  {match.distance_km !== null
                    ? t('lot.kmAway', { km: number(match.distance_km) })
                    : '—'}
                </td>
                <td className="px-3 py-2 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => navigate(`/lots/${match.entity_id}`)}
                  >
                    {t('app.viewAll')}
                  </Button>
                </td>
              </tr>
            ))}
          </Table>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card
          title={t('dash.openDemands')}
          action={
            <Button onClick={() => navigate('/my-demands')}>{t('demand.new')}</Button>
          }
          padded={false}
        >
          {data.open_demands.length === 0 ? (
            <EmptyState title={t('app.noResults')} hint={t('demand.createHint')} />
          ) : (
            <Table
              caption={t('dash.openDemands')}
              columns={[
                t('lot.commodity'),
                t('demand.required'),
                t('demand.requiredBy'),
                t('status.label'),
              ]}
            >
              {data.open_demands.map((demand) => (
                <tr key={demand.id} className="hover:bg-stone-50">
                  <td className="px-3 py-2">
                    <p className="font-medium text-stone-900">{demand.commodity_name}</p>
                    <p className="text-xs text-stone-500">{demand.reference_code}</p>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                    {number(demand.required_quantity)} <UnitLabel unit={demand.unit} />
                  </td>
                  <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                    {demand.required_by_date}
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge value={demand.status} tone={demandTone(demand.status)} />
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title={t('dash.pipeline')}>
          <PipelineBar buckets={data.orders.length ? summarise(data.orders) : []} />
        </Card>
      </div>

      <Card
        title={t('dash.yourOrders')}
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate('/orders')}>
            {t('app.viewAll')}
          </Button>
        }
        padded={false}
      >
        {data.orders.length === 0 ? (
          <EmptyState title={t('order.noOrders')} hint={t('order.noOrdersHint')} />
        ) : (
          <Table
            caption={t('dash.yourOrders')}
            columns={[
              t('order.number'),
              t('lot.commodity'),
              t('order.total'),
              t('status.label'),
              t('order.paymentStatus'),
            ]}
          >
            {data.orders.map((order) => (
              <tr key={order.id} className="hover:bg-stone-50">
                <td className="px-3 py-2 font-medium whitespace-nowrap text-stone-900">
                  {order.order_number}
                </td>
                <td className="px-3 py-2 text-stone-700">{order.commodity_name}</td>
                <td className="px-3 py-2 whitespace-nowrap">{money(order.total_value)}</td>
                <td className="px-3 py-2">
                  <StatusBadge value={order.status} tone={orderTone(order.status)} domain="order" />
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={order.payment_status} tone={paymentTone(order.payment_status)} />
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  )
}

/**
 * The overview reports a median modal price across markets; a price card shows
 * the modal rate, the range and a 7-day direction. The conversion is explicit
 * here rather than pretending the two shapes are the same.
 */
function overviewToCard(row: CommodityOverviewRow): PriceCard {
  const change = row.change_pct_7d ?? 0
  return {
    commodity_id: row.commodity_id,
    commodity_name: row.commodity,
    unit: row.unit,
    modal_price: row.median_modal_price,
    min_price: row.min_modal,
    max_price: row.max_modal,
    // The overview has no single price date: it is a snapshot of the latest rows.
    price_date: null,
    arrivals_quintal: null,
    change_pct_7d: row.change_pct_7d,
    trend: change > 0.5 ? 'up' : change < -0.5 ? 'down' : 'flat',
    my_lots: 0,
    market_count: row.market_count,
  }
}

/** Rolls the recent orders into the same bucket shape the pipeline endpoint returns. */
function summarise(
  orders: Array<{ status: string; total_value: number }>,
): Array<{ status: never; count: number; value: number }> {
  const buckets = new Map<string, { count: number; value: number }>()
  for (const order of orders) {
    const existing = buckets.get(order.status) ?? { count: 0, value: 0 }
    existing.count += 1
    existing.value += order.total_value
    buckets.set(order.status, existing)
  }
  return [...buckets.entries()].map(([status, data]) => ({
    status: status as never,
    count: data.count,
    value: data.value,
  }))
}
