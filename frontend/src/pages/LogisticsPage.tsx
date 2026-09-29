/**
 * Transport requests.
 *
 * Quotes come from `/logistics/quotes`, which returns indicative costs flagged
 * `is_demo`. Those are shown with the same warning as market prices, because a
 * demo freight quote is just as capable of being believed.
 */

import { useState } from 'react'

import { useAuth } from '../auth/AuthContext'
import { useAsync } from '../hooks'
import { logistics as logisticsApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Badge, Card, EmptyState, ErrorState, Loading, Paginator, Table, cx } from '../components/ui'
import { Button } from '../components/form'
import { StatusBadge } from '../components/labels'
import { DemoBanner } from '../components/dashboardParts'
import type { LogisticsQuoteOption, LogisticsRequest, Page } from '../lib/types'

export function LogisticsPage() {
  const { t, number, money, date } = useI18n()
  const { can, hasRole } = useAuth()
  const [page, setPage] = useState(1)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)

  const requests = useAsync<Page<LogisticsRequest>>(
    async () => logisticsApi.list({ page }),
    { deps: [page] },
  )

  const isPartner = hasRole('LOGISTICS_PARTNER')

  async function assign(request: LogisticsRequest) {
    setBusyId(request.id)
    setActionError(null)
    try {
      await logisticsApi.assign(request.id, {})
      requests.reload()
    } catch (cause) {
      setActionError(cause)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-stone-900">{t('logistics.title')}</h1>

      {actionError ? <ErrorState error={actionError} /> : null}

      {requests.initialLoading ? (
        <Loading />
      ) : requests.error ? (
        <ErrorState error={requests.error} onRetry={requests.reload} />
      ) : !requests.data || requests.data.items.length === 0 ? (
        <Card>
          <EmptyState title={t('logistics.noRequests')} />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={t('logistics.title')}
            columns={[
              t('logistics.reference'),
              t('logistics.pickup'),
              t('logistics.destination'),
              t('logistics.distance'),
              t('logistics.vehicle'),
              t('logistics.cost'),
              t('status.label'),
              '',
            ]}
          >
            {requests.data.items.map((request) => (
              <tr key={request.id}>
                <td className="px-3 py-2 font-medium whitespace-nowrap text-stone-900">
                  {request.reference_code}
                  {request.cold_chain_required && (
                    <Badge tone="info">{t('logistics.coldChain')}</Badge>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  {request.pickup_location}
                  {request.pickup_district ? `, ${request.pickup_district}` : ''}
                  <span className="block text-stone-400">{date(request.pickup_date)}</span>
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  {request.destination}
                  {request.destination_district ? `, ${request.destination_district}` : ''}
                  <span className="block text-stone-400">{date(request.delivery_date)}</span>
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-600">
                  {request.distance_km !== null ? `${number(request.distance_km)} km` : '—'}
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  {request.vehicle_type ?? '—'}
                  {request.vehicle_number && (
                    <span className="block text-stone-400">{request.vehicle_number}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-700">
                  {request.estimated_cost !== null ? money(request.estimated_cost) : '—'}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={request.status} />
                </td>
                <td className="px-3 py-2 text-right">
                  {can('logistics:assign') && !request.provider_user_id && (
                    <Button size="sm" busy={busyId === request.id} onClick={() => void assign(request)}>
                      {t('logistics.assign')}
                    </Button>
                  )}
                  {request.tracking_number && (
                    <span className="text-xs text-stone-500">
                      {t('logistics.tracking')}: {request.tracking_number}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <div className="px-4">
            <Paginator meta={requests.data.meta} onPage={setPage} />
          </div>
        </Card>
      )}

      {!isPartner && can('logistics:request') && <RequestTransportCard />}
    </div>
  )
}

/** Asks for indicative quotes on an order; demo quotes are labelled as such. */
function RequestTransportCard() {
  const { t, money, number } = useI18n()
  const [orderId, setOrderId] = useState('')
  const [quotes, setQuotes] = useState<LogisticsQuoteOption[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function loadQuotes(event: React.FormEvent) {
    event.preventDefault()
    if (!orderId) return
    setBusy(true)
    setError(null)
    try {
      setQuotes(await logisticsApi.quote({ order_id: orderId }))
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }

  const anyDemo = quotes?.some((quote) => quote.is_demo) ?? false

  return (
    <Card title={t('logistics.requestQuote')}>
      <form onSubmit={loadQuotes} className="space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-48 flex-1">
            <label className="block text-sm font-medium text-stone-700" htmlFor="order-id">
              {t('order.number')}
            </label>
            <input
              id="order-id"
              value={orderId}
              onChange={(event) => setOrderId(event.target.value)}
              className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2 text-sm"
              placeholder="00000000-0000-0000-0000-000000000000"
            />
          </div>
          <Button type="submit" busy={busy}>
            {t('logistics.requestQuote')}
          </Button>
        </div>
      </form>

      {error ? <div className="mt-3"><ErrorState error={error} /></div> : null}

      {quotes && (
        <div className="mt-4 space-y-2">
          {anyDemo && <DemoBanner />}
          {quotes.length === 0 ? (
            <EmptyState title={t('logistics.noQuotes')} />
          ) : (
            quotes.map((quote) => (
              <div
                key={`${quote.provider_name}-${quote.vehicle_type}`}
                className={cx(
                  'flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm',
                  anyDemo ? 'border-amber-200 bg-amber-50' : 'border-stone-200',
                )}
              >
                <div>
                  <p className="font-medium text-stone-900">{quote.provider_name}</p>
                  <p className="text-xs text-stone-500">
                    {quote.vehicle_type} · {number(quote.distance_km)} km ·{' '}
                    {t('logistics.transitDays', { days: quote.transit_days })}
                    {quote.rating !== null && ` · ★ ${number(quote.rating)}`}
                  </p>
                </div>
                <p className="font-semibold text-stone-900">{money(quote.estimated_cost)}</p>
              </div>
            ))
          )}
        </div>
      )}
    </Card>
  )
}
