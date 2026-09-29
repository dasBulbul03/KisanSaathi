/**
 * Payments.
 *
 * A payment is modelled in two places in the backend: a `Transaction` (the
 * trade) and a `Payment` (the money movement against it). This screen shows
 * payments, because that is what a user is looking for — did I get paid, who owes
 * me — and the summary tiles come from `/payments/summary`.
 *
 * The summary endpoint returns an untyped dict, so these fields are read
 * defensively: a missing key renders as an em dash rather than "undefined".
 */

import { useState } from 'react'

import { useAsync } from '../hooks'
import { payments as paymentsApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Paginator,
  Table,
  cx,
  paymentTone,
} from '../components/ui'
import { Button } from '../components/form'
import { StatusBadge } from '../components/labels'
import { StatTile } from '../components/dashboardParts'
import type { Page, Payment } from '../lib/types'

function amount(summary: Record<string, unknown> | null, ...keys: string[]): number {
  if (!summary) return 0
  for (const key of keys) {
    const value = summary[key]
    if (typeof value === 'number') return value
  }
  return 0
}
/**
 * The moment a payment was recorded as settled. Kept out of the component so the
 * timestamp is stamped by the click handler and nowhere near render.
 */
function settledNow() {
  return { status: 'PAID' as const, paid_at: new Date().toISOString() }
}


export function PaymentsPage() {
  const { t, money, date, moneyCompact } = useI18n()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)

  const summary = useAsync(async () => paymentsApi.summary())
  const list = useAsync<Page<Payment>>(
    async () => paymentsApi.list({ page, ...(status ? { status } : {}) }),
    { deps: [page, status] },
  )

  async function markPaid(payment: Payment) {
    setBusyId(payment.id)
    setActionError(null)
    try {
      await paymentsApi.updateStatus(payment.id, settledNow())
      list.reload()
      summary.reload()
    } catch (cause) {
      setActionError(cause)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-stone-900">{t('payment.title')}</h1>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label={t('payment.totalExpected')}
          value={moneyCompact(amount(summary.data, 'total_expected', 'expected'))}
        />
        <StatTile
          label={t('payment.totalPaid')}
          value={moneyCompact(amount(summary.data, 'total_paid', 'paid'))}
          tone="positive"
        />
        <StatTile
          label={t('payment.totalPending')}
          value={moneyCompact(amount(summary.data, 'total_pending', 'pending'))}
          tone="warning"
        />
        <StatTile
          label={t('payment.overdue')}
          value={moneyCompact(amount(summary.data, 'overdue_amount'))}
          tone={amount(summary.data, 'overdue_amount') > 0 ? 'negative' : 'default'}
        />
      </div>

      <Card>
        <div className="flex flex-wrap gap-2">
          {['', 'PENDING', 'PROCESSING', 'PAID', 'FAILED', 'DISPUTED'].map((value) => (
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
          ))}
        </div>
      </Card>

      {actionError ? <ErrorState error={actionError} /> : null}

      {list.initialLoading ? (
        <Loading />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={list.reload} />
      ) : !list.data || list.data.items.length === 0 ? (
        <Card>
          <EmptyState title={t('payment.noPayments')} hint={t('payment.noPaymentsHint')} />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={t('payment.title')}
            columns={[
              t('order.number'),
              t('order.party.buyer'),
              t('order.party.seller'),
              t('payment.amount'),
              t('payment.dueDate'),
              t('status.label'),
              '',
            ]}
          >
            {list.data.items.map((payment) => (
              <tr key={payment.id}>
                <td className="px-3 py-2 font-medium whitespace-nowrap text-stone-900">
                  {payment.order_number ?? payment.transaction_reference}
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">{payment.payer_name ?? '—'}</td>
                <td className="px-3 py-2 text-xs text-stone-700">{payment.payee_name ?? '—'}</td>
                <td className="px-3 py-2 whitespace-nowrap font-medium">
                  {money(payment.amount)}
                  {payment.is_demo && (
                    <span className="ml-1.5 text-xs text-amber-700">demo</span>
                  )}
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                  {date(payment.due_date)}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={payment.status} tone={paymentTone(payment.status)} />
                  {payment.failure_reason && (
                    <span className="block text-xs text-red-700">
                      {t('payment.failureReason')}: {payment.failure_reason}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {payment.status !== 'PAID' && (
                    <Button
                      size="sm"
                      busy={busyId === payment.id}
                      onClick={() => void markPaid(payment)}
                    >
                      {t('payment.markPaid')}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <div className="px-4">
            <Paginator meta={list.data.meta} onPage={setPage} />
          </div>
        </Card>
      )}
    </div>
  )
}
