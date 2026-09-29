/**
 * Read-only demand view.
 *
 * Sellers and admins reach this page from the match list on a lot, and buyers
 * reach it from the open-demand table. Buyers also have the editable form at
 * `/my-demands/:id`; this page deliberately shows only what a counterparty
 * should see, so a seller cannot walk into the buyer's edit screen.
 */

import { useNavigate, useParams } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { useAsync } from '../hooks'
import { demands as demandsApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Card, EmptyState, ErrorState, Loading } from '../components/ui'
import { Button } from '../components/form'
import { GradeBadge, StatusBadge, UnitLabel } from '../components/labels'
import type { BuyerDemand } from '../lib/types'

export function DemandDetailPage() {
  const { id = '' } = useParams()
  const { t, number, date, money } = useI18n()
  const { can } = useAuth()
  const navigate = useNavigate()

  const demand = useAsync<BuyerDemand>(async () => demandsApi.get(id), { deps: [id] })

  if (demand.initialLoading) return <Loading />
  if (demand.error) return <ErrorState error={demand.error} onRetry={demand.reload} />
  if (!demand.data) return <EmptyState title={t('app.noResults')} />

  const data = demand.data
  // The API allows nulls for quantities on older records, so treat them as zero
  // rather than rendering "null" into a progress bar.
  const required = data.required_quantity ?? 0
  const fulfilled = data.fulfilled_quantity ?? 0
  const windowDays = data.delivery_window_days ?? 0
  const paymentDays = data.payment_terms_days ?? 0
  const radius = data.max_pickup_radius_km ?? 0
  const progress = required > 0 ? (fulfilled / required) * 100 : 0

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          {t('app.back')}
        </Button>
        {can('demand:update') && (
          <Button size="sm" onClick={() => navigate(`/my-demands/${data.id}`)}>
            {t('demand.edit')}
          </Button>
        )}
      </div>

      <Card
        title={data.commodity_name}
        subtitle={data.reference_code}
        action={<StatusBadge value={data.status} tone={data.status === 'OPEN' ? 'success' : 'neutral'} domain="demand" />}
      >
        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          <Row label={t('demand.required')}>
            {number(required)} <UnitLabel unit={data.unit} />
          </Row>
          <Row label={t('demand.minGrade')}>
            <GradeBadge grade={data.min_grade} />
          </Row>
          <Row label={t('demand.deliveryLocation')}>{data.delivery_location}</Row>
          <Row label={t('lot.district')}>{data.district ?? '—'}</Row>
          <Row label={t('demand.requiredBy')}>{date(data.required_by_date)}</Row>
          <Row label={t('demand.window')}>
            {t('demand.days', { days: windowDays })}
          </Row>
          <Row label={t('demand.maxPrice')}>
            {data.max_price_per_unit ? `${money(data.max_price_per_unit)} / ${data.unit}` : '—'}
          </Row>
          <Row label={t('demand.paymentTerms')}>
            {t('demand.days', { days: paymentDays })}
          </Row>
          <Row label={t('demand.radius')}>
            {t('lot.kmAway', { km: radius })}
          </Row>
          <Row label={t('demand.buyer')}>{data.buyer_organisation ?? data.buyer_name}</Row>
        </dl>

        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between text-xs text-stone-500">
            <span>{t('demand.fulfilled')}</span>
            <span className="tabular">
              {number(fulfilled)} / {number(required)}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-stone-100">
            <div
              className="h-full rounded-full bg-emerald-600"
              style={{ width: `${Math.min(100, progress)}%` }}
            />
          </div>
        </div>

        {data.notes ? (
          <p className="mt-4 whitespace-pre-wrap text-sm text-stone-700">{data.notes}</p>
        ) : null}
      </Card>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-stone-500">{label}</dt>
      <dd className="text-sm text-stone-900">{children}</dd>
    </div>
  )
}
