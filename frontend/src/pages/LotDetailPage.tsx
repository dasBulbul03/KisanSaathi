/**
 * Lot detail: the page where a trade is decided.
 *
 * Buyers get the market price for the same commodity alongside the lot's asking
 * price, because an asking price on its own gives them nothing to compare it
 * against. Sellers see the matching demands instead, which is their side of the
 * same decision.
 *
 * Making an offer, accepting one, and publishing a lot are all real state
 * changes, so each is behind a confirmation: accepting an offer creates a
 * binding order, which is not something to do with a stray tap.
 */

import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { useAsync } from '../hooks'
import { lots as lotsApi, markets, offers as offersApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Table,
  cx,
  lotTone,
  offerTone,
} from '../components/ui'
import { Button, TextArea, TextInput } from '../components/form'
import { GradeBadge, StatusBadge, UnitLabel } from '../components/labels'
import { DemoBanner } from '../components/dashboardParts'
import type { FarmLot, MatchResult, Offer, PriceSnapshot } from '../lib/types'

export function LotDetailPage({ scope }: { scope: 'browse' | 'mine' }) {
  const { id = '' } = useParams()
  const { t, number, money, date } = useI18n()
  const navigate = useNavigate()
  const { can, profile } = useAuth()

  const isSeller = scope === 'mine'
  const lot = useAsync<FarmLot>(async () => lotsApi.get(id), { deps: [id] })

  // Only a buyer may see market comparison and make an offer.
  const asBuyer = can('offer:create')
  const asSeller = can('lot:update_own')

  const [offerOpen, setOfferOpen] = useState(false)
  const [offerPrice, setOfferPrice] = useState('')
  const [offerQuantity, setOfferQuantity] = useState('')
  const [offerNotes, setOfferNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const snapshot = useAsync<PriceSnapshot>(
    async () =>
      lot.data?.commodity_id
        ? markets.priceSnapshot(lot.data.commodity_id)
        : { commodity_id: '', commodity_name: null, unit: null, as_of: '', markets: [] },
    { enabled: Boolean(lot.data?.commodity_id), deps: [lot.data?.commodity_id] },
  )
  // The snapshot wraps rows in an object, so pages read the `markets` array.
  const marketRows = snapshot.data?.markets ?? []

  const matchingDemands = useAsync<MatchResult[]>(
    async () => (asSeller ? lotsApi.matches(id) : []),
    { enabled: asSeller, deps: [id] },
  )

  const lotOffers = useAsync<Offer[]>(
    async () => (asSeller ? offersApi.forLot(id) : Promise.resolve([])),
    { enabled: asSeller, deps: [id] },
  )

  if (lot.initialLoading) return <Loading />
  if (lot.error) return <ErrorState error={lot.error} onRetry={lot.reload} />
  const data = lot.data
  if (!data) return null

  const canOffer = asBuyer && data.status === 'PUBLISHED' && data.available_quantity > 0
  const canPublish = asSeller && data.status === 'DRAFT'
  const ownLot = data.seller_user_id === profile?.user.id

  // Declared after the null guard so the closures below keep the narrowed type
  // of `data`; a hoisted `function` would not.
  const runAction = async (action: () => Promise<unknown>, successMessage?: string) => {
    setBusy(true)
    setActionError(null)
    try {
      await action()
      if (successMessage) setNotice(successMessage)
      lot.reload()
      lotOffers.reload()
      matchingDemands.reload()
    } catch (cause) {
      setActionError(cause)
    } finally {
      setBusy(false)
    }
  }

  const submitOffer = async (event: React.FormEvent) => {
    event.preventDefault()
    const price = Number(offerPrice)
    const quantity = Number(offerQuantity)
    await runAction(() =>
      offersApi.create({
        lot_id: data.id,
        offered_price: price,
        quantity,
        ...(offerNotes.trim() ? { notes: offerNotes.trim() } : {}),
      }),
    )
    setOfferOpen(false)
    setOfferPrice('')
    setOfferQuantity('')
    setOfferNotes('')
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          {t('app.back')}
        </Button>
        {ownLot && asSeller && (
          <Button size="sm" variant="secondary" onClick={() => navigate(`/my-lots/${id}/edit`)}>
            {t('lot.edit')}
          </Button>
        )}
      </div>

      {actionError ? <ErrorState error={actionError} /> : null}
      {notice ? (
        <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          {notice}
        </p>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="text-lg font-semibold text-stone-900">{data.title}</h1>
                <p className="text-sm text-stone-500">
                  {data.lot_code} · {data.commodity_name} · {data.commodity_category}
                </p>
              </div>
              <StatusBadge value={data.status} tone={lotTone(data.status)} domain="lot" />
            </div>

            <dl className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <Field label={t('lot.quantity')} value={`${number(data.available_quantity)} ${data.unit}`} />
              <Field
                label={t('lot.grade')}
                value={
                  <span className="flex items-center gap-2">
                    <GradeBadge grade={data.quality_grade} />
                    {data.inspection_grade && (
                      <span className="text-xs text-stone-500">
                        {t('lot.quality.inspected')}: {data.inspection_grade}
                      </span>
                    )}
                  </span>
                }
              />
              <Field
                label={t('lot.expectedPrice')}
                value={data.expected_price ? money(data.expected_price) : '—'}
              />
              <Field
                label={t('lot.minPrice')}
                value={data.minimum_price ? money(data.minimum_price) : '—'}
              />
              <Field
                label={t('lot.harvestDate')}
                value={date(data.harvest_date)}
              />
              <Field
                label={t('lot.availableFrom')}
                value={date(data.available_from)}
              />
              <Field
                label={t('lot.location')}
                value={[data.village, data.taluka, data.district, data.state]
                  .filter(Boolean)
                  .join(', ')}
              />
              <Field label={t('lot.viewCount')} value={number(data.view_count)} />
              <Field label={t('lot.offersCount')} value={number(data.active_offers_count)} />
            </dl>

            {data.description && (
              <div className="mt-4 border-t border-stone-100 pt-3">
                <p className="text-xs font-medium text-stone-500">{t('lot.description')}</p>
                <p className="mt-1 text-sm text-stone-700">{data.description}</p>
              </div>
            )}

            <div className="mt-4 flex flex-wrap gap-2 border-t border-stone-100 pt-3">
              {data.organic_certified && <Badge tone="success">{t('lot.organic')}</Badge>}
              {data.storage_available && <Badge tone="info">{t('lot.storage')}</Badge>}
              {data.pickup_available && <Badge>{t('lot.pickup')}</Badge>}
              {data.seller_handles_transport && <Badge>{t('lot.selfTransport')}</Badge>}
            </div>
          </Card>

          {asSeller && lotOffers.data && lotOffers.data.length > 0 && (
            <Card title={t('offer.onLot')} padded={false}>
              <Table
                caption={t('offer.onLot')}
                columns={[
                  t('order.party.buyer'),
                  t('offer.price'),
                  t('offer.quantity'),
                  t('offer.validUntil'),
                  t('status.label'),
                  '',
                ]}
              >
                {lotOffers.data.map((offer) => (
                  <tr key={offer.id}>
                    <td className="px-3 py-2">
                      <p className="font-medium text-stone-900">
                        {offer.buyer_organisation ?? offer.buyer_name}
                      </p>
                      {offer.buyer_verified && (
                        <Badge tone="success">{t('offer.verifiedBuyer')}</Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">{money(offer.offered_price)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {number(offer.quantity)} <UnitLabel unit={offer.unit} />
                    </td>
                    <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                      {date(offer.valid_until)}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge value={offer.status} tone={offerTone(offer.status)} domain="offer" />
                    </td>
                    <td className="px-3 py-2 text-right">
                      {offer.can_respond && offer.status === 'PENDING' && (
                        <span className="flex justify-end gap-1">
                          <Button
                            size="sm"
                            busy={busy}
                            onClick={() =>
                              void runAction(() => offersApi.accept(offer.id), t('offer.accept'))
                            }
                          >
                            {t('offer.accept')}
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            busy={busy}
                            onClick={() => {
                              const reason = window.prompt(t('offer.rejectReason'))
                              if (reason) {
                                void runAction(() => offersApi.reject(offer.id, reason))
                              }
                            }}
                          >
                            {t('offer.reject')}
                          </Button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </Table>
            </Card>
          )}

          {asSeller && matchingDemands.data && matchingDemands.data.length > 0 && (
            <Card
              title={t('lot.matches')}
              action={
                <p className="text-xs text-stone-500">{t('match.disclaimer')}</p>
              }
              padded={false}
            >
              <Table
                caption={t('lot.matches')}
                columns={[
                  t('demand.title'),
                  t('demand.required'),
                  t('match.score'),
                  t('demand.requiredBy'),
                  '',
                ]}
              >
                {matchingDemands.data.map((match) => (
                  <tr key={match.entity_id}>
                    <td className="px-3 py-2">
                      <p className="font-medium text-stone-900">
                        {match.title ?? match.reference_code}
                      </p>
                      <p className="text-xs text-stone-500">
                        {match.seller_organisation ?? match.seller_name}
                        {match.is_verified_buyer && (
                          <span className="ml-1.5 text-emerald-700">
                            {t('offer.verifiedBuyer')}
                          </span>
                        )}
                      </p>
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                      {number(match.quantity)} <UnitLabel unit={match.unit} />
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className="font-medium">{number(match.score)}</span>
                      <span className="ml-1 text-xs text-stone-500">
                        {t(`match.${match.score_label.toLowerCase()}` as never)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                      {date(match.required_by_date)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => navigate(`/demands/${match.entity_id}`)}
                      >
                        {t('app.viewAll')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </Table>
            </Card>
          )}
        </div>

        <div className="space-y-5">
          {data.seller && (
            <Card title={t('order.party.seller')}>
              <p className="font-medium text-stone-900">
                {data.seller.organisation_name ?? data.seller.full_name}
              </p>
              <p className="text-sm text-stone-500">
                {[data.seller.village, data.seller.district].filter(Boolean).join(', ')}
              </p>
              {data.seller.is_verified && (
                <Badge tone="success">{t('profile.verified')}</Badge>
              )}
            </Card>
          )}

          {/* Market price for the same commodity: the comparison a buyer needs. */}
          <Card
            title={t('lot.marketPrice')}
            action={
              marketRows.some((price) => price.is_demo) ? (
                <span className="text-xs text-amber-700">{t('app.demoBanner')}</span>
              ) : null
            }
          >
            {snapshot.initialLoading ? (
              <Loading />
            ) : marketRows.length === 0 ? (
              <EmptyState title={t('app.noResults')} />
            ) : (
              <>
                {marketRows.some((price) => price.is_demo) && <DemoBanner />}
                <ul className="space-y-2">
                  {marketRows.slice(0, 6).map((price) => (
                    <li
                      key={price.market_id}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-stone-700">{price.market_name}</span>
                      <span className="font-medium text-stone-900">
                        {money(price.modal_price)}
                      </span>
                    </li>
                  ))}
                </ul>
                {data.latest_market_price && (
                  <div className="mt-3 border-t border-stone-100 pt-3">
                    <Field
                      label={t('market.modal')}
                      value={money(data.latest_market_price.modal_price)}
                    />
                  </div>
                )}
              </>
            )}
          </Card>

          <Card title={t('offer.new')}>
            {!ownLot && !canOffer ? (
              <EmptyState title={t('app.noResults')} hint={t('app.noResultsHint')} />
            ) : (
              <div className="space-y-3">
                {canPublish && (
                  <Button
                    className="w-full"
                    busy={busy}
                    onClick={() => void runAction(() => lotsApi.publish(id), t('lot.published'))}
                  >
                    {t('lot.publish')}
                  </Button>
                )}

                {canOffer && !offerOpen && (
                  <Button className="w-full" onClick={() => setOfferOpen(true)}>
                    {t('offer.new')}
                  </Button>
                )}

                {canOffer && offerOpen && (
                  <form onSubmit={submitOffer} className="space-y-3">
                    <TextInput
                      label={t('offer.price')}
                      value={offerPrice}
                      onChange={setOfferPrice}
                      type="number"
                      inputMode="decimal"
                      min={1}
                      step="0.01"
                      required
                    />
                    <TextInput
                      label={t('offer.quantity')}
                      value={offerQuantity}
                      onChange={setOfferQuantity}
                      type="number"
                      inputMode="decimal"
                      min={1}
                      required
                      hint={`${t('lot.available')}: ${number(data.available_quantity)}`}
                    />
                    <TextArea
                      label={t('order.note')}
                      value={offerNotes}
                      onChange={setOfferNotes}
                      rows={2}
                    />
                    <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900">
                      {t('offer.acceptHint')}
                    </p>
                    <div className="flex gap-2">
                      <Button type="submit" busy={busy} className="flex-1">
                        {t('offer.new')}
                      </Button>
                      <Button variant="secondary" onClick={() => setOfferOpen(false)}>
                        {t('app.cancel')}
                      </Button>
                    </div>
                  </form>
                )}

                {isSeller && ownLot && data.status !== 'DRAFT' && (
                  <Button
                    variant="danger"
                    className="w-full"
                    busy={busy}
                    onClick={() => {
                      const reason = window.prompt(t('order.cancelReason'))
                      if (reason) void runAction(() => lotsApi.cancel(id, reason))
                    }}
                  >
                    {t('lot.cancelLot')}
                  </Button>
                )}
              </div>
            )}
          </Card>

          {data.quality_specs && Object.keys(data.quality_specs).length > 0 && (
            <Card title={t('lot.qualitySpecs')}>
              <dl className="space-y-1.5 text-sm">
                {Object.entries(data.quality_specs).map(([key, value]) => (
                  <div key={key} className="flex justify-between gap-3">
                    <dt className="text-stone-500">{key}</dt>
                    <dd className="text-stone-800">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-stone-500">{label}</dt>
      <dd className={cx('mt-0.5 text-sm text-stone-900')}>{value}</dd>
    </div>
  )
}
