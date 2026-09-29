/**
 * Farmer / FPO dashboard.
 *
 * `is_demo_data` drives the banner. That flag comes from the server, which
 * detects seeded `MarketPrice.source == 'DEMO'` rows, so the warning appears
 * on a freshly seeded database and disappears once real data is synced. It is
 * deliberately hard to miss: a demo price mistaken for a real one could cost a
 * farmer money.
 */

import { useNavigate } from 'react-router-dom'

import { useAsync } from '../hooks'
import { dashboards } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  StatGrid,
  Table,
  cx,
  lotTone,
  offerTone,
} from '../components/ui'
import { Button } from '../components/form'
import { GradeBadge, StatusBadge, UnitLabel } from '../components/labels'
import {
  DemoBanner,
  InsightList,
  PipelineBar,
  PriceCardRow,
  StatTile,
} from '../components/dashboardParts'
import type { FarmerDashboard } from '../lib/types'

export default function FarmerDashboardPage() {
  const { t, number, money, date, relative } = useI18n()
  const navigate = useNavigate()

  const state = useAsync<FarmerDashboard>(async () => dashboards.farmer())

  if (state.initialLoading) return <Loading />
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />
  const data = state.data
  if (!data) return null

  const firstName = data.seller.full_name.split(' ')[0]

  return (
    <div className="space-y-5">
      {data.is_demo_data && <DemoBanner />}

      <header>
        <h1 className="text-xl font-semibold text-stone-900">
          {t('dash.greeting.farmer', { name: firstName })}
        </h1>
        <p className="text-sm text-stone-500">
          {data.seller.district ?? ''}
          {data.seller.village ? ` · ${data.seller.village}` : ''}
          {data.seller.organisation_name ? ` · ${data.seller.organisation_name}` : ''}
        </p>
      </header>

      <StatGrid>
        {data.stats.map((stat) => (
          <StatTile
            key={stat.label}
            label={stat.label}
            value={stat.display || number(stat.value)}
            hint={stat.hint}
            tone={
              stat.trend === 'up'
                ? 'positive'
                : stat.trend === 'down'
                  ? 'negative'
                  : stat.change_pct != null && stat.change_pct < 0
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
        padded={false}
      >
        <div className="p-4">
          {data.price_cards.length === 0 ? (
            <EmptyState title={t('app.noResults')} />
          ) : (
            <PriceCardRow cards={data.price_cards} />
          )}
        </div>
      </Card>

      {data.insights.length > 0 && (
        <Card title={t('dash.insights')}>
          <InsightList insights={data.insights} />
        </Card>
      )}

      <Card
        title={t('dash.activeLots')}
        action={
          <Button onClick={() => navigate('/my-lots')}>{t('lot.new')}</Button>
        }
        padded={false}
      >
        {data.active_lots.length === 0 ? (
          <EmptyState
            title={t('dash.noLots')}
            hint={t('dash.noLotsHint')}
            action={
              <Button onClick={() => navigate('/my-lots')}>{t('dash.listLot')}</Button>
            }
          />
        ) : (
          <>
            <Table
              caption={t('dash.activeLots')}
              columns={[
                t('lot.title'),
                t('lot.quantity'),
                t('lot.grade'),
                t('lot.expectedPrice'),
                t('lot.status'),
                '',
              ]}
            >
              {data.active_lots.map((lot) => (
                <tr key={lot.id} className="hover:bg-stone-50">
                  <td className="px-3 py-2">
                    <p className="font-medium text-stone-900">{lot.title}</p>
                    <p className="text-xs text-stone-500">
                      {lot.lot_code} · {lot.commodity_name}
                    </p>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                    {number(lot.available_quantity)}{' '}
                    <UnitLabel unit={lot.unit} />
                  </td>
                  <td className="px-3 py-2">
                    <GradeBadge grade={lot.quality_grade} />
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                    {lot.expected_price ? money(lot.expected_price) : '—'}
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge value={lot.status} tone={lotTone(lot.status)} domain="lot" />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => navigate(`/lots/${lot.id}`)}
                    >
                      {t('app.viewAll')}
                    </Button>
                  </td>
                </tr>
              ))}
            </Table>
          </>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card
          title={t('dash.recentOffers')}
          action={
            <Button variant="ghost" size="sm" onClick={() => navigate('/offers')}>
              {t('app.viewAll')}
            </Button>
          }
          padded={false}
        >
          {data.recent_offers.length === 0 ? (
            <EmptyState title={t('offer.noOffers')} hint={t('offer.noOffersHint')} />
          ) : (
            <Table
              caption={t('dash.recentOffers')}
              columns={[
                t('offer.forLot'),
                t('offer.price'),
                t('offer.quantity'),
                t('status.label'),
                t('market.date'),
              ]}
            >
              {data.recent_offers.map((offer) => (
                <tr key={offer.id} className="hover:bg-stone-50">
                  <td className="px-3 py-2">
                    <p className="font-medium text-stone-900">{offer.lot_title ?? '—'}</p>
                    <p className="text-xs text-stone-500">{offer.reference_code}</p>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {money(offer.offered_price)}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                    {number(offer.quantity)} <UnitLabel unit={offer.unit} />
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge value={offer.status} tone={offerTone(offer.status)} domain="offer" />
                  </td>
                  <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                    {relative(offer.created_at)}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title={t('dash.pipeline')}>
          <PipelineBar buckets={data.order_pipeline} />
        </Card>
      </div>

      {data.notifications.length > 0 && (
        <Card
          title={t('notification.title')}
          action={
            <Button variant="ghost" size="sm" onClick={() => navigate('/notifications')}>
              {t('app.viewAll')}
            </Button>
          }
          padded={false}
        >
          <ul className="divide-y divide-stone-100">
            {data.notifications.slice(0, 5).map((item) => (
              <li key={item.id} className="px-4 py-3">
                <p
                  className={cx(
                    'text-sm',
                    item.is_read ? 'text-stone-600' : 'font-medium text-stone-900',
                  )}
                >
                  {item.title}
                </p>
                <p className="mt-0.5 text-xs text-stone-500">{item.body}</p>
                <p className="mt-0.5 text-xs text-stone-400">{date(item.created_at)}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
