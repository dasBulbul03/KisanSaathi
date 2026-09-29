/**
 * Orders.
 *
 * The status advance is not a free-text field: the backend exposes
 * `/orders/{id}/allowed-transitions`, and the screen renders exactly that list.
 * That keeps the valid order lifecycle on the server where it belongs, and means
 * a role can never be offered a transition the API will refuse.
 *
 * `status_history` is rendered as a timeline because "where is my order" is the
 * question this page is opened to answer.
 */

import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { useAsync } from '../hooks'
import { orders as ordersApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Paginator,
  Table,
  cx,
  orderTone,
  paymentTone,
} from '../components/ui'
import { Button } from '../components/form'
import { StatusBadge, UnitLabel } from '../components/labels'
import type { Order, Page } from '../lib/types'

export function OrdersPage() {
  const { t, number, money, date } = useI18n()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')

  const result = useAsync<Page<Order>>(
    async () => ordersApi.list({ page, ...(status ? { status } : {}) }),
    { deps: [page, status] },
  )

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-stone-900">{t('nav.orders')}</h1>

      <Card>
        <div className="flex flex-wrap gap-2">
          {['', 'ORDER_CREATED', 'PICKUP_SCHEDULED', 'IN_TRANSIT', 'DELIVERED', 'PAYMENT_PENDING', 'COMPLETED', 'CANCELLED'].map(
            (value) => (
              <button
                key={value || 'all'}
                type="button"
                onClick={() => {
                  setStatus(value)
                  setPage(1)
                }}
                className={cx(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  status === value
                    ? 'bg-emerald-700 text-white'
                    : 'bg-white text-stone-700 ring-1 ring-stone-300 ring-inset hover:bg-stone-50',
                )}
              >
                {value ? t(`status.${value}` as never) : t('app.all')}
              </button>
            ),
          )}
        </div>
      </Card>

      {result.initialLoading ? (
        <Loading />
      ) : result.error ? (
        <ErrorState error={result.error} onRetry={result.reload} />
      ) : !result.data || result.data.items.length === 0 ? (
        <Card>
          <EmptyState title={t('order.noOrders')} hint={t('order.noOrdersHint')} />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={t('nav.orders')}
            columns={[
              t('order.number'),
              t('lot.commodity'),
              t('order.quantity'),
              t('order.total'),
              t('order.pickupDate'),
              t('status.label'),
              t('order.paymentStatus'),
            ]}
          >
            {result.data.items.map((order) => (
              <tr
                key={order.id}
                className="cursor-pointer hover:bg-stone-50"
                onClick={() => navigate(`/orders/${order.id}`)}
              >
                <td className="px-3 py-2 font-medium whitespace-nowrap text-stone-900">
                  {order.order_number}
                </td>
                <td className="px-3 py-2 text-stone-700">{order.commodity_name}</td>
                <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                  {number(order.quantity)} <UnitLabel unit={order.unit} />
                </td>
                <td className="px-3 py-2 whitespace-nowrap">{money(order.total_value)}</td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                  {date(order.pickup_date)}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={order.status} tone={orderTone(order.status)} domain="order" />
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={order.payment_status} tone={paymentTone(order.payment_status)} />
                </td>
              </tr>
            ))}
          </Table>
          <div className="px-4">
            <Paginator meta={result.data.meta} onPage={setPage} />
          </div>
        </Card>
      )}
    </div>
  )
}

export function OrderDetailPage() {
  const { id = '' } = useParams()
  const { t, number, money, date, dateTime } = useI18n()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const order = useAsync<Order>(async () => ordersApi.get(id), { deps: [id] })
  const transitions = useAsync<string[]>(
    async () => ordersApi.transitions(id),
    { deps: [id] },
  )

  if (order.initialLoading) return <Loading />
  if (order.error) return <ErrorState error={order.error} onRetry={order.reload} />
  const data = order.data
  if (!data) return null

  async function advance(status: string) {
    const note = window.prompt(t('order.note')) ?? undefined
    setBusy(true)
    setError(null)
    try {
      await ordersApi.updateStatus(id, status, note)
      order.reload()
      transitions.reload()
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
        {t('app.back')}
      </Button>

      {error ? <ErrorState error={error} /> : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          title={`${t('order.number')} ${data.order_number}`}
          className="lg:col-span-2"
          action={
            <StatusBadge value={data.status} tone={orderTone(data.status)} domain="order" />
          }
        >
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            <Field label={t('lot.commodity')} value={data.commodity_name} />
            <Field
              label={t('order.quantity')}
              value={`${number(data.quantity)} ${data.unit}`}
            />
            <Field label={t('order.price')} value={money(data.agreed_price)} />
            <Field label={t('order.total')} value={money(data.total_value)} />
            <Field
              label={t('order.pickup')}
              value={[data.pickup_location, data.pickup_district].filter(Boolean).join(', ')}
            />
            <Field
              label={t('order.delivery')}
              value={[data.delivery_location, data.delivery_district]
                .filter(Boolean)
                .join(', ')}
            />
            <Field label={t('order.pickupDate')} value={date(data.pickup_date)} />
            <Field label={t('order.deliveryDate')} value={date(data.delivery_date)} />
            <Field
              label={t('order.paymentTerms')}
              value={data.payment_terms_days !== null ? t('demand.days', { days: data.payment_terms_days }) : '—'}
            />
            <Field label={t('order.paymentDue')} value={date(data.payment_due_date)} />
            <Field label={t('order.party.buyer')} value={data.buyer_organisation ?? data.buyer_name} />
            <Field
              label={t('order.party.seller')}
              value={data.seller_organisation ?? data.seller_name}
            />
            {data.logistics_reference && (
              <Field label={t('order.logisticsRef')} value={data.logistics_reference} />
            )}
          </dl>

          {data.cancelled_reason && (
            <p className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-800">
              {t('order.cancelReason')}: {data.cancelled_reason}
            </p>
          )}

          {transitions.data && transitions.data.length > 0 && (
            <div className="mt-4 border-t border-stone-100 pt-3">
              <p className="mb-2 text-xs font-medium text-stone-500">
                {t('order.updateStatus')}
              </p>
              <div className="flex flex-wrap gap-2">
                {transitions.data.map((status) => (
                  <Button
                    key={status}
                    size="sm"
                    variant="secondary"
                    busy={busy}
                    onClick={() => void advance(status)}
                  >
                    {t(`status.${status}` as never)}
                  </Button>
                ))}
              </div>
            </div>
          )}
        </Card>

        <Card title={t('order.history')}>
          {!data.status_history || data.status_history.length === 0 ? (
            <EmptyState title={t('app.noResults')} />
          ) : (
            <ol className="space-y-3">
              {[...data.status_history].reverse().map((entry, index) => (
                <li key={`${entry.status}-${index}`} className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <span
                      className={cx(
                        'mt-1 size-2.5 rounded-full',
                        index === 0 ? 'bg-emerald-600' : 'bg-stone-300',
                      )}
                    />
                    {index < data.status_history!.length - 1 && (
                      <span className="w-px flex-1 bg-stone-200" />
                    )}
                  </div>
                  <div className="pb-1">
                    <p className="text-sm font-medium text-stone-800">
                      {t(`status.${entry.status}` as never)}
                    </p>
                    <p className="text-xs text-stone-500">{dateTime(entry.at)}</p>
                    {entry.by && <p className="text-xs text-stone-500">{entry.by}</p>}
                    {entry.note && <p className="mt-0.5 text-xs text-stone-600">{entry.note}</p>}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
    </div>
  )
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-stone-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-stone-900">{value}</dd>
    </div>
  )
}
