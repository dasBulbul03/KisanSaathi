/**
 * Demand lists and the create/edit form.
 *
 * `min_grade` is a floor, not a preference: a seller whose produce is Grade B
 * does not match a demand asking for A. The form's hint says so, because a buyer
 * who sets it by accident will wonder why no offers arrive.
 */

import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { useAsync } from '../hooks'
import { demands as demandsApi, markets } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Badge, Card, EmptyState, ErrorState, Loading, Paginator, Table, demandTone } from '../components/ui'
import { Button, Checkbox, Select, TextArea, TextInput } from '../components/form'
import { GradeBadge, StatusBadge, UnitLabel } from '../components/labels'
import type { BuyerDemand, Commodity, Page } from '../lib/types'

export function DemandsPage({ scope }: { scope: 'browse' | 'mine' }) {
  const { t, number, date } = useI18n()
  const navigate = useNavigate()
  const { can } = useAuth()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')

  const isMine = scope === 'mine'
  const result = useAsync<Page<BuyerDemand>>(
    async () =>
      isMine
        ? demandsApi.mine({ page })
        : demandsApi.list({ page, ...(status ? { status } : {}) }),
    { deps: [scope, page, status] },
  )

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-stone-900">
          {isMine ? t('nav.demands') : t('nav.browseDemands')}
        </h1>
        {isMine && can('demand:create') && (
          <Button onClick={() => navigate('/my-demands/new')}>{t('demand.new')}</Button>
        )}
      </header>

      {!isMine && (
        <Card>
          <Select
            label={t('lot.status')}
            value={status}
            onChange={(value) => {
              setStatus(value)
              setPage(1)
            }}
            options={['OPEN', 'PARTIALLY_FULFILLED', 'FULFILLED', 'CLOSED'].map((value) => ({
              value,
              label: t(`status.${value}` as never),
            }))}
            placeholder={t('app.all')}
          />
        </Card>
      )}

      {result.initialLoading ? (
        <Loading />
      ) : result.error ? (
        <ErrorState error={result.error} onRetry={result.reload} />
      ) : !result.data || result.data.items.length === 0 ? (
        <Card>
          <EmptyState
            title={t('demand.noMatches')}
            hint={t('demand.createHint')}
            action={
              isMine && can('demand:create') ? (
                <Button onClick={() => navigate('/my-demands/new')}>{t('demand.new')}</Button>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={t('demand.title')}
            columns={[
              t('lot.commodity'),
              t('demand.required'),
              t('demand.minGrade'),
              t('order.party.buyer'),
              t('demand.deliveryLocation'),
              t('demand.requiredBy'),
              t('status.label'),
            ]}
          >
            {result.data.items.map((demand) => (
              <tr
                key={demand.id}
                className="cursor-pointer hover:bg-stone-50"
                onClick={() => navigate(isMine ? `/my-demands/${demand.id}` : `/demands/${demand.id}`)}
              >
                <td className="px-3 py-2">
                  <p className="font-medium text-stone-900">{demand.commodity_name}</p>
                  <p className="text-xs text-stone-500">{demand.reference_code}</p>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                  {number(demand.required_quantity)} <UnitLabel unit={demand.unit} />
                </td>
                <td className="px-3 py-2">
                  <GradeBadge grade={demand.min_grade} />
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  {isMine ? (
                    '—'
                  ) : (
                    <>
                      <p>{demand.buyer_organisation ?? demand.buyer_name}</p>
                      {demand.buyer_verified && (
                        <Badge tone="success">{t('offer.verifiedBuyer')}</Badge>
                      )}
                    </>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-stone-600">
                  {demand.delivery_location}
                  {demand.district ? `, ${demand.district}` : ''}
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                  {date(demand.required_by_date)}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={demand.status} tone={demandTone(demand.status)} />
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

const GRADES = ['A', 'B', 'C'] as const

const UNIT_FALLBACK = ['quintal', 'kg', 'tonne']

export function DemandFormPage() {
  const { id } = useParams()
  const isEdit = Boolean(id)
  const { t, number, date } = useI18n()
  const navigate = useNavigate()

  const existing = useAsync<BuyerDemand>(
    async () => demandsApi.get(id as string),
    { enabled: isEdit, deps: [id] },
  )

  const commodities = useAsync<Commodity[]>(async () => markets.commodities())

  const [commodityId, setCommodityId] = useState('')
  const [quantity, setQuantity] = useState('')
  const [unit, setUnit] = useState('quintal')
  const [minGrade, setMinGrade] = useState<string>('B')
  const [maxPrice, setMaxPrice] = useState('')
  const [location, setLocation] = useState('')
  const [district, setDistrict] = useState('')
  const [requiredBy, setRequiredBy] = useState('')
  const [window, setWindow] = useState('7')
  const [radius, setRadius] = useState('50')
  const [paymentDays, setPaymentDays] = useState('7')
  const [verifiedOnly, setVerifiedOnly] = useState(false)
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [hydrated, setHydrated] = useState(!isEdit)

  // Prefill once from the fetched demand; `hydrated` stops it overwriting edits
  // on a re-fetch.
  if (isEdit && existing.data && !hydrated) {
    const demand = existing.data
    setCommodityId(demand.commodity_id)
    setQuantity(String(demand.required_quantity))
    setUnit(demand.unit)
    setMinGrade(demand.min_grade)
    setMaxPrice(demand.max_price_per_unit ? String(demand.max_price_per_unit) : '')
    setLocation(demand.delivery_location)
    setDistrict(demand.district ?? '')
    setRequiredBy(demand.required_by_date)
    setWindow(String(demand.delivery_window_days ?? 7))
    setRadius(String(demand.max_pickup_radius_km ?? 50))
    setPaymentDays(String(demand.payment_terms_days ?? 7))
    setVerifiedOnly(Boolean(demand.requires_verified_buyer))
    setNotes(demand.notes ?? '')
    setHydrated(true)
  }

  const selectedCommodity = commodities.data?.find((c) => c.id === commodityId)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const body: Record<string, unknown> = {
      commodity_id: commodityId,
      required_quantity: Number(quantity),
      unit,
      min_grade: minGrade,
      delivery_location: location.trim(),
      district: district.trim() || undefined,
      required_by_date: requiredBy,
      delivery_window_days: Number(window) || undefined,
      max_pickup_radius_km: Number(radius) || undefined,
      payment_terms_days: Number(paymentDays) || undefined,
      requires_verified_buyer: verifiedOnly,
      ...(maxPrice ? { max_price_per_unit: Number(maxPrice) } : {}),
      ...(notes.trim() ? { notes: notes.trim() } : {}),
    }
    try {
      if (isEdit) await demandsApi.update(id as string, body)
      else await demandsApi.create(body)
      navigate('/my-demands')
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }

  if (isEdit && existing.initialLoading) return <Loading />
  if (existing.error) return <ErrorState error={existing.error} onRetry={existing.reload} />

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
        {t('app.back')}
      </Button>

      <Card title={isEdit ? t('demand.edit') : t('demand.new')}>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Select
            label={t('lot.commodity')}
            value={commodityId}
            onChange={setCommodityId}
            required
            placeholder={t('form.selectCommodity')}
            options={(commodities.data ?? []).map((commodity) => ({
              value: commodity.id,
              label: `${commodity.name} (${commodity.category})`,
            }))}
          />

          <div className="grid gap-4 sm:grid-cols-2">
            <TextInput
              label={t('demand.required')}
              value={quantity}
              onChange={setQuantity}
              type="number"
              inputMode="decimal"
              min={1}
              required
            />
            <Select
              label={t('lot.unit')}
              value={unit}
              onChange={setUnit}
              options={(selectedCommodity?.permitted_units ?? UNIT_FALLBACK).map(
                (value) => ({ value, label: value.toLowerCase() }),
              )}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label={t('demand.minGrade')}
              value={minGrade}
              onChange={setMinGrade}
              required
              options={GRADES.map((value) => ({ value, label: t(`status.${value}` as never) }))}
              hint={t('lot.quality.selfReported')}
            />
            <TextInput
              label={t('demand.maxPrice')}
              value={maxPrice}
              onChange={setMaxPrice}
              type="number"
              inputMode="decimal"
              min={1}
              placeholder="0"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <TextInput
              label={t('demand.deliveryLocation')}
              value={location}
              onChange={setLocation}
              required
            />
            <TextInput label={t('lot.district')} value={district} onChange={setDistrict} />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <TextInput
              label={t('demand.requiredBy')}
              value={requiredBy}
              onChange={setRequiredBy}
              type="date"
              required
            />
            <TextInput
              label={t('demand.window')}
              value={window}
              onChange={setWindow}
              type="number"
              inputMode="numeric"
              min={1}
            />
            <TextInput
              label={t('demand.radius')}
              value={radius}
              onChange={setRadius}
              type="number"
              inputMode="numeric"
              min={1}
            />
          </div>

          <TextInput
            label={t('order.paymentTerms')}
            value={paymentDays}
            onChange={setPaymentDays}
            type="number"
            inputMode="numeric"
            min={0}
            hint={t('demand.days', { days: paymentDays || '0' })}
          />

          <Checkbox
            label={t('demand.verifiedOnly')}
            checked={verifiedOnly}
            onChange={setVerifiedOnly}
          />

          <TextArea
            label={t('demand.notes')}
            value={notes}
            onChange={setNotes}
            rows={3}
          />

          {error ? <ErrorState error={error} /> : null}

          <div className="flex gap-2">
            <Button type="submit" busy={busy} className="flex-1">
              {isEdit ? t('app.save') : t('demand.new')}
            </Button>
            <Button variant="secondary" onClick={() => navigate('/my-demands')}>
              {t('app.cancel')}
            </Button>
          </div>
        </form>
      </Card>

      {isEdit && existing.data && (
        <p className="text-xs text-stone-400">
          {t('demand.fulfilled')}: {number(existing.data.fulfilled_quantity ?? 0)} ·{' '}
          {t('offer.count')}: {number(existing.data.active_offers_count ?? 0)} ·{' '}
          {t('user.joined')}: {date(existing.data.created_at)}
        </p>
      )}
    </div>
  )
}
