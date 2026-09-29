/**
 * Grievances.
 *
 * A grievance is the user-facing escape hatch when something goes wrong on an
 * order, so the raise form is reachable from the orders context rather than
 * buried. Escalation exists because a user who does not hear back needs a way to
 * push, not just to complain.
 */

import { useState } from 'react'

import { useAsync } from '../hooks'
import { grievances as grievanceApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Badge, Card, EmptyState, ErrorState, Loading, Paginator, Table, cx } from '../components/ui'
import { Button, Select, TextArea, TextInput } from '../components/form'
import { StatusBadge } from '../components/labels'
import type { Grievance, Page } from '../lib/types'

const CATEGORIES = [
  { value: 'PAYMENT', label: 'Payment' },
  { value: 'QUALITY', label: 'Quality' },
  { value: 'DELIVERY_DELAY', label: 'Delivery delay' },
  { value: 'QUANTITY_SHORT', label: 'Quantity short' },
  { value: 'QUALITY_DISPUTE', label: 'Quality dispute' },
  { value: 'PAYMENT_DEFAULT', label: 'Buyer did not pay' },
  { value: 'OTHER', label: 'Other' },
]

export function GrievancesPage() {
  const { t, date } = useI18n()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [raising, setRaising] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)

  const list = useAsync<Page<Grievance>>(
    async () => grievanceApi.list({ page, ...(status ? { status } : {}) }),
    { deps: [page, status] },
  )

  async function escalate(id: string) {
    const reason = window.prompt(t('grievance.escalateReason'))
    if (!reason) return
    setBusyId(id)
    setActionError(null)
    try {
      await grievanceApi.escalate(id, reason)
      list.reload()
    } catch (cause) {
      setActionError(cause)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-stone-900">{t('grievance.title')}</h1>
        <Button onClick={() => setRaising((open) => !open)}>
          {raising ? t('app.close') : t('grievance.raise')}
        </Button>
      </div>

      {raising && <RaiseForm onDone={() => { setRaising(false); list.reload() }} />}

      <Card>
        <div className="flex flex-wrap gap-2">
          {['', 'OPEN', 'UNDER_REVIEW', 'RESOLVED', 'ESCALATED', 'REJECTED'].map((value) => (
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
          <EmptyState title={t('grievance.noGrievances')} hint={t('grievance.noGrievancesHint')} />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={t('grievance.title')}
            columns={[
              t('grievance.ticket'),
              t('grievance.subject'),
              t('grievance.category'),
              t('grievance.priority'),
              t('status.label'),
              t('market.date'),
              '',
            ]}
          >
            {list.data.items.map((grievance) => (
              <tr key={grievance.id}>
                <td className="px-3 py-2 font-medium whitespace-nowrap text-stone-900">
                  {grievance.ticket_number}
                </td>
                <td className="px-3 py-2 text-stone-800">{grievance.subject}</td>
                <td className="px-3 py-2 text-xs text-stone-600">
                  {grievance.category.replace(/_/g, ' ')}
                </td>
                <td className="px-3 py-2">
                  <Badge tone={grievance.priority === 'URGENT' ? 'danger' : 'neutral'}>
                    {t(`status.${grievance.priority}` as never)}
                  </Badge>
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={grievance.status} />
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                  {date(grievance.created_at)}
                </td>
                <td className="px-3 py-2 text-right">
                  {grievance.status === 'OPEN' && (
                    <Button size="sm" variant="ghost" busy={busyId === grievance.id}
                      onClick={() => void escalate(grievance.id)}>
                      {t('grievance.escalate')}
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

function RaiseForm({ onDone }: { onDone: () => void }) {
  const { t } = useI18n()
  const [category, setCategory] = useState('PAYMENT')
  const [subject, setSubject] = useState('')
  const [description, setDescription] = useState('')
  const [orderId, setOrderId] = useState('')
  const [priority, setPriority] = useState('MEDIUM')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await grievanceApi.create({
        category,
        subject: subject.trim(),
        description: description.trim(),
        priority,
        ...(orderId.trim() ? { order_id: orderId.trim() } : {}),
      })
      onDone()
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title={t('grievance.raise')}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select
            label={t('grievance.category')}
            value={category}
            onChange={setCategory}
            options={CATEGORIES}
          />
          <Select
            label={t('grievance.priority')}
            value={priority}
            onChange={setPriority}
            options={['LOW', 'MEDIUM', 'HIGH', 'URGENT'].map((value) => ({
              value,
              label: t(`status.${value}` as never),
            }))}
          />
        </div>
        <TextInput label={t('grievance.subject')} value={subject} onChange={setSubject} required />
        <TextArea
          label={t('grievance.description')}
          value={description}
          onChange={setDescription}
          required
          rows={4}
        />
        <TextInput
          label={t('order.number')}
          value={orderId}
          onChange={setOrderId}
          hint={t('app.optional')}
        />
        {error ? <ErrorState error={error} /> : null}
        <Button type="submit" busy={busy}>
          {t('grievance.raise')}
        </Button>
      </form>
    </Card>
  )
}
