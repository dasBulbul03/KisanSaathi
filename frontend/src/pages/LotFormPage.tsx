/**
 * Lot create and edit form.
 *
 * A lot is the seller's whole offer, so the form asks for what a buyer needs to
 * judge it (commodity, quantity, grade, price, location) and keeps logistics
 * preferences as switches rather than fields, since farmers arrive on a phone
 * and only the two price fields really need typing.
 *
 * Draft vs published is the one decision with real consequences: `publish_now`
 * makes the lot visible to buyers, while a draft stays private so the seller can
 * finish it later. The toggle is on the create screen only, because publishing
 * is a deliberate one-way action on the detail page.
 */

import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { useAsync } from '../hooks'
import { lots as lotsApi, markets } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Card, ErrorState, Loading } from '../components/ui'
import { Button, Checkbox, Select, TextArea, TextInput } from '../components/form'
import { useUnitLabel } from '../components/labels'
import type { Commodity, FarmLot, PriceSnapshot } from '../lib/types'

const GRADES = ['A', 'B', 'C'] as const
const UNIT_FALLBACK = ['quintal', 'kg', 'tonne']

export function LotFormPage() {
  const { id } = useParams()
  const isEdit = Boolean(id)
  const { t } = useI18n()
  const unitLabel = useUnitLabel()
  const navigate = useNavigate()

  const existing = useAsync<FarmLot>(async () => lotsApi.get(id as string), {
    enabled: isEdit,
    deps: [id],
  })
  const commodities = useAsync<Commodity[]>(async () => markets.commodities())

  const [commodityId, setCommodityId] = useState('')
  const [title, setTitle] = useState('')
  const [quantity, setQuantity] = useState('')
  const [unit, setUnit] = useState('quintal')
  const [grade, setGrade] = useState<string>('A')
  const [expectedPrice, setExpectedPrice] = useState('')
  const [minimumPrice, setMinimumPrice] = useState('')
  const [harvestDate, setHarvestDate] = useState('')
  const [availableFrom, setAvailableFrom] = useState('')
  const [village, setVillage] = useState('')
  const [taluka, setTaluka] = useState('')
  const [district, setDistrict] = useState('')
  const [storageAvailable, setStorageAvailable] = useState(false)
  const [organic, setOrganic] = useState(false)
  const [pickupAvailable, setPickupAvailable] = useState(true)
  const [selfTransport, setSelfTransport] = useState(true)
  const [description, setDescription] = useState('')
  const [publishNow, setPublishNow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [hydrated, setHydrated] = useState(!isEdit)

  // Prefill once. Adjusting state during render is deliberate here: it happens
  // in the same pass the fetched lot arrives, so the form never paints with
  // empty fields and then overwrites what the seller has already typed.
  if (isEdit && existing.data && !hydrated) {
    const lot = existing.data
    setCommodityId(lot.commodity_id)
    setTitle(lot.title)
    setQuantity(String(lot.quantity))
    setUnit(lot.unit)
    setGrade(lot.quality_grade)
    setExpectedPrice(lot.expected_price ? String(lot.expected_price) : '')
    setMinimumPrice(lot.minimum_price ? String(lot.minimum_price) : '')
    setHarvestDate(lot.harvest_date ?? '')
    setAvailableFrom(lot.available_from ?? '')
    setVillage(lot.village ?? '')
    setTaluka(lot.taluka ?? '')
    setDistrict(lot.district ?? '')
    setStorageAvailable(Boolean(lot.storage_available))
    setOrganic(Boolean(lot.organic_certified))
    setPickupAvailable(lot.pickup_available ?? true)
    setSelfTransport(lot.seller_handles_transport ?? true)
    setDescription(lot.description ?? '')
    setHydrated(true)
  }

  const selectedCommodity = commodities.data?.find((c) => c.id === commodityId)
  const market = useAsync<PriceSnapshot>(
    async () =>
      commodityId
        ? markets.priceSnapshot(commodityId)
        : { commodity_id: '', commodity_name: null, unit: null, as_of: '', markets: [] },
    { enabled: Boolean(commodityId), deps: [commodityId] },
  )
  // A benchmark the seller can compare their asking price against. The highest
  // modal price across markets is the realistic ceiling, so use that rather than
  // an average that no single market pays.
  const benchmark = market.data?.markets.reduce<number | null>(
    (best, row) => (best === null || row.modal_price > best ? row.modal_price : best),
    null,
  )

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const qty = Number(quantity)
    const expected = expectedPrice ? Number(expectedPrice) : null
    const minimum = minimumPrice ? Number(minimumPrice) : null

    if (!commodityId || !title.trim() || !(qty > 0)) {
      setError(new Error(t('form.pleaseFix')))
      return
    }
    // The API rejects this too, but catching it here keeps the message next to
    // the fields instead of in an error banner.
    if (minimum !== null && expected !== null && minimum > expected) {
      setError(new Error(t('lot.priceOrderError')))
      return
    }

    setBusy(true)
    setError(null)
    const location = {
      village: village.trim() || undefined,
      taluka: taluka.trim() || undefined,
      district: district.trim() || undefined,
    }
    const shared = {
      quantity: qty,
      unit,
      quality_grade: grade,
      expected_price: expected,
      minimum_price: minimum,
      harvest_date: harvestDate || null,
      available_from: availableFrom || null,
      storage_available: storageAvailable,
      organic_certified: organic,
      pickup_available: pickupAvailable,
      seller_handles_transport: selfTransport,
      description: description.trim() || null,
    }
    const body: Record<string, unknown> = isEdit
      ? { ...shared, title: title.trim() }
      : {
          ...shared,
          title: title.trim(),
          commodity_id: commodityId,
          ...location,
          publish_now: publishNow,
        }

    try {
      const saved = isEdit
        ? await lotsApi.update(id as string, body)
        : await lotsApi.create(body)
      navigate(`/my-lots/${saved.id}`, { replace: true })
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

      <Card
        title={isEdit ? t('lot.edit') : t('lot.new')}
        subtitle={isEdit ? undefined : t('lot.newHint')}
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <Select
            label={t('lot.commodity')}
            value={commodityId}
            onChange={setCommodityId}
            required
            disabled={isEdit}
            options={(commodities.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
            hint={isEdit ? t('lot.commodityLocked') : undefined}
          />

          <TextInput
            label={t('lot.title')}
            value={title}
            onChange={setTitle}
            required
            placeholder={t('lot.titlePlaceholder')}
          />

          <div className="grid gap-4 sm:grid-cols-3">
            <TextInput
              label={t('lot.quantity')}
              type="number"
              min="0.1"
              step="0.1"
              value={quantity}
              onChange={setQuantity}
              required
            />
            <Select
              label={t('lot.unit')}
              value={unit}
              onChange={setUnit}
              options={(selectedCommodity?.permitted_units ?? UNIT_FALLBACK).map((value) => ({
                value,
                label: unitLabel(value),
              }))}
            />
            <Select
              label={t('lot.grade')}
              value={grade}
              onChange={setGrade}
              options={GRADES.map((value) => ({ value, label: t(`status.${value}` as never) }))}
              hint={t('lot.quality.selfReported')}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <TextInput
              label={t('lot.expectedPrice')}
              type="number"
              min="0"
              step="0.01"
              value={expectedPrice}
              onChange={setExpectedPrice}
              hint={benchmark ? t('lot.priceHint') : undefined}
            />
            <TextInput
              label={t('lot.minPrice')}
              type="number"
              min="0"
              step="0.01"
              value={minimumPrice}
              onChange={setMinimumPrice}
              hint={t('lot.minPriceHint')}
            />
          </div>

          {benchmark ? (
            <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
              <span className="font-medium">{t('lot.benchmarkPrice')}: </span>
              {`\u20b9${benchmark} / ${unitLabel(unit)}`}
            </p>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <TextInput
              label={t('lot.harvestDate')}
              type="date"
              value={harvestDate}
              onChange={setHarvestDate}
            />
            <TextInput
              label={t('lot.availableFrom')}
              type="date"
              value={availableFrom}
              onChange={setAvailableFrom}
            />
          </div>

          {!isEdit && (
            <div className="grid gap-4 sm:grid-cols-3">
              <TextInput
                label={t('lot.village')}
                value={village}
                onChange={setVillage}
              />
              <TextInput
                label={t('lot.taluka')}
                value={taluka}
                onChange={setTaluka}
              />
              <TextInput
                label={t('lot.district')}
                value={district}
                onChange={setDistrict}
                required
              />
            </div>
          )}

          <TextArea
            label={t('lot.description')}
            value={description}
            onChange={setDescription}
            rows={3}
            maxLength={2000}
            hint={t('lot.descriptionHint')}
          />

          <div className="space-y-3 rounded-lg border border-stone-200 p-3">
            <Checkbox
              label={t('lot.storage')}
              checked={storageAvailable}
              onChange={setStorageAvailable}
            />
            <Checkbox label={t('lot.organic')} checked={organic} onChange={setOrganic} />
            <Checkbox
              label={t('lot.pickup')}
              checked={pickupAvailable}
              onChange={setPickupAvailable}
            />
            <Checkbox
              label={t('lot.selfTransport')}
              checked={selfTransport}
              onChange={setSelfTransport}
            />
          </div>

          {!isEdit && (
            <Checkbox
              label={t('lot.publishNow')}
              hint={t('lot.publishHint')}
              checked={publishNow}
              onChange={setPublishNow}
            />
          )}

          {error ? <ErrorState error={error} compact /> : null}

          <div className="flex gap-2">
            <Button type="submit" busy={busy}>
              {isEdit ? t('app.save') : t('lot.new')}
            </Button>
            <Button type="button" variant="secondary" onClick={() => navigate(-1)}>
              {t('app.cancel')}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
