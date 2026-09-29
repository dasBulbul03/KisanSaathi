/**
 * Market prices.
 *
 * The demo warning here is the most important thing on the screen. Seeded prices
 * are plausible-looking numbers, and a farmer deciding what to ask for could
 * easily treat them as real. The backend flags every seeded row (`is_demo`), the
 * trend and comparison endpoints carry their own `disclaimer`, and all three are
 * surfaced rather than hidden behind a tooltip.
 *
 * The trend is a plain inline SVG rather than a chart library: it is one series
 * of modal prices over a date axis, and drawing it directly keeps the bundle
 * small and the axes labelled in the active language.
 */

import { useMemo, useState } from 'react'

import { useAsync } from '../hooks'
import { markets } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Card, EmptyState, ErrorState, Loading, Table, cx } from '../components/ui'
import { Select } from '../components/form'
import { DemoBanner } from '../components/dashboardParts'
import { UnitLabel } from '../components/labels'
import type { Commodity, MarketComparison, MarketPriceTrend, PriceSnapshot } from '../lib/types'

export function MarketPage() {
  const { t, number, money, date } = useI18n()
  const [commodityId, setCommodityId] = useState('')
  const [district, setDistrict] = useState('')
  const [days, setDays] = useState('30')

  const commodities = useAsync<Commodity[]>(async () => markets.commodities())
  const districts = useAsync<string[]>(async () => markets.districts())

  const snapshot = useAsync<PriceSnapshot>(
    async () =>
      commodityId
        ? markets.priceSnapshot(commodityId, district || undefined)
        : { commodity_id: '', commodity_name: null, unit: null, as_of: '', markets: [] },
    { enabled: Boolean(commodityId), deps: [commodityId, district] },
  )
  // The endpoint returns `{as_of, markets: [...]}`; rows live under `markets`.
  const snapshotRows = useMemo(() => snapshot.data?.markets ?? [], [snapshot.data])
  const trend = useAsync<MarketPriceTrend>(
    async () => markets.trend(commodityId, Number(days) || 30, district || undefined),
    { enabled: Boolean(commodityId), deps: [commodityId, days, district] },
  )
  const comparison = useAsync<MarketComparison>(
    async () => markets.comparison(commodityId, district || undefined),
    { enabled: Boolean(commodityId), deps: [commodityId, district] },
  )

  const isDemo = useMemo(
    () =>
      snapshotRows.some((price) => price.is_demo) ||
      trend.data?.is_demo_data ||
      comparison.data?.is_demo_data ||
      false,
    [snapshotRows, trend.data, comparison.data],
  )

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-stone-900">{t('market.title')}</h1>

      {isDemo && <DemoBanner />}

      <Card>
        <div className="grid gap-3 sm:grid-cols-3">
          <Select
            label={t('market.commodity')}
            value={commodityId}
            onChange={setCommodityId}
            required
            placeholder={t('form.selectCommodity')}
            options={(commodities.data ?? []).map((commodity) => ({
              value: commodity.id,
              label: commodity.name,
            }))}
          />
          <Select
            label={t('market.district')}
            value={district}
            onChange={setDistrict}
            placeholder={t('market.allDistricts')}
            options={(districts.data ?? []).map((value) => ({ value, label: value }))}
          />
          <Select
            label={t('market.trend')}
            value={days}
            onChange={setDays}
            options={['7', '30', '90', '180'].map((value) => ({
              value,
              label: `${value} ${t('app.of')}`,
            }))}
          />
        </div>
      </Card>

      {!commodityId ? (
        <Card>
          <EmptyState
            title={t('market.chooseCommodity')}
            hint={t('market.demoNotice')}
          />
        </Card>
      ) : (
        <>
          <Card title={t('market.trend')}>
            {trend.initialLoading ? (
              <Loading />
            ) : trend.error ? (
              <ErrorState error={trend.error} onRetry={trend.reload} />
            ) : !trend.data || trend.data.points.length < 2 ? (
              <EmptyState title={t('market.noTrend')} />
            ) : (
              <>
                <TrendChart trend={trend.data} />
                <div className="mt-3 flex flex-wrap gap-4 text-sm">
                  <span className="text-stone-600">
                    {t('market.districtMedian')}:{' '}
                    <strong className="text-stone-900">
                      {money(trend.data.district_median_modal_price)}
                    </strong>
                  </span>
                  {trend.data.overall_change_pct !== null && (
                    <span
                      className={cx(
                        'font-medium',
                        trend.data.overall_change_pct >= 0
                          ? 'text-emerald-700'
                          : 'text-red-700',
                      )}
                    >
                      {t('dash.priceChange')}: {trend.data.overall_change_pct > 0 ? '+' : ''}
                      {number(trend.data.overall_change_pct)}%
                    </span>
                  )}
                </div>
                <p className="mt-2 text-xs text-stone-400">{trend.data.disclaimer}</p>
              </>
            )}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={t('dash.priceToday')} padded={false}>
              {snapshot.initialLoading ? (
                <Loading />
              ) : snapshotRows.length === 0 ? (
                <EmptyState title={t('app.noResults')} />
              ) : (
                <Table
                  caption={t('dash.priceToday')}
                  columns={[
                    t('user.district'),
                    t('market.min'),
                    t('market.modal'),
                    t('market.highest'),
                    t('market.date'),
                  ]}
                >
                  {snapshotRows.map((price) => (
                    <tr key={price.market_id}>
                      <td className="px-3 py-2 text-stone-800">{price.market_name}</td>
                      <td className="px-3 py-2 text-stone-700">{money(price.min_price)}</td>
                      <td className="px-3 py-2 font-medium text-stone-900">
                        {money(price.modal_price)}
                      </td>
                      <td className="px-3 py-2 text-stone-700">{money(price.max_price)}</td>
                      <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                        {date(price.date)}
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </Card>

            <Card title={t('market.compare')} padded={false}>
              {comparison.initialLoading ? (
                <Loading />
              ) : !comparison.data || comparison.data.rows.length === 0 ? (
                <EmptyState title={t('app.noResults')} />
              ) : (
                <Table
                  caption={t('market.compare')}
                  columns={[
                    t('user.district'),
                    t('market.modal'),
                    t('lot.distance'),
                    t('market.arrivals'),
                  ]}
                >
                  {comparison.data.rows.map((row) => (
                    <tr
                      key={row.market_id}
                      className={cx(
                        row.market_id === comparison.data?.best_market_id && 'bg-emerald-50',
                      )}
                    >
                      <td className="px-3 py-2 text-stone-800">
                        {row.market_name}
                        {row.market_id === comparison.data?.best_market_id && (
                          <span className="ml-1.5 text-xs text-emerald-700">
                            {t('market.best')}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 font-medium text-stone-900">
                        {money(row.modal_price)}
                      </td>
                      <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-600">
                        {row.distance_km !== null
                          ? t('lot.kmAway', { km: number(row.distance_km) })
                          : '—'}
                      </td>
                      <td className="px-3 py-2 text-xs text-stone-600">
                        {row.arrivals_quantity !== null ? number(row.arrivals_quantity) : '—'}
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </Card>
          </div>

          {trend.data && (
            <p className="text-xs text-stone-400">
              <UnitLabel unit={trend.data.unit} long /> · {t('market.from')} {date(trend.data.from_date)}{' '}
              – {date(trend.data.to_date)}
            </p>
          )}
        </>
      )}
    </div>
  )
}

/**
 * Modal price over time. The y-axis is scaled to the data's own range with a
 * little padding, because the meaningful signal in a price series is the shape,
 * not the absolute level.
 */
function TrendChart({ trend }: { trend: MarketPriceTrend }) {
  const { t, money, date, number } = useI18n()
  const points = trend.points

  const { min, max } = points.reduce(
    (acc, point) => ({
      min: Math.min(acc.min, point.modal_price),
      max: Math.max(acc.max, point.modal_price),
    }),
    { min: Number.POSITIVE_INFINITY, max: Number.NEGATIVE_INFINITY },
  )
  // A flat series would make the divisor zero.
  const spread = max - min || 1
  const pad = spread * 0.1

  const width = 640
  const height = 180
  const step = points.length > 1 ? width / (points.length - 1) : width

  const coords = points.map((point, index) => ({
    x: index * step,
    y: height - ((point.modal_price - (min - pad)) / (spread + pad * 2)) * height,
    point,
  }))

  const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')
  const area = `${path} L${width},${height} L0,${height} Z`

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-44 w-full"
        role="img"
        aria-label={`${t('market.trend')}: ${t('market.modal')} ${min} – ${max}`}
      >
        <defs>
          <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#059669" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#059669" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#priceFill)" />
        <path
          d={path}
          fill="none"
          stroke="#047857"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {coords.map((c) => (
          <circle key={c.point.date} cx={c.x} cy={c.y} r="2.5" fill="#047857">
            <title>
              {date(c.point.date)}: {money(c.point.modal_price)}
            </title>
          </circle>
        ))}
      </svg>
      <div className="mt-1 flex justify-between text-xs text-stone-500">
        <span>{date(points[0]?.date)}</span>
        <span>
          {t('market.min')} {money(min)} · {t('market.highest')} {money(max)}
        </span>
        <span>{date(points[points.length - 1]?.date)}</span>
      </div>
      <p className="sr-only">
        {points.length} {t('market.date')}, {number(points.length)}
      </p>
    </div>
  )
}
