/**
 * Offers.
 *
 * A seller and a buyer see the same list with different meaning, so the columns
 * switch on `is_buyer` rather than on role: the party the caller is not is
 * always the one worth naming. `can_respond` comes from the backend and is the
 * only thing that decides whether action buttons appear, so the UI never offers
 * an action the API will reject.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAsync } from '../hooks'
import { offers as offersApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Badge, Card, EmptyState, ErrorState, Loading, Paginator, Table, offerTone } from '../components/ui'
import { Button } from '../components/form'
import { StatusBadge, UnitLabel } from '../components/labels'
import type { Offer, Page } from '../lib/types'

export function OffersPage() {
  const { t, number, money, relative } = useI18n()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const result = useAsync<Page<Offer>>(
    async () => offersApi.list({ page, ...(status ? { status } : {}) }),
    { deps: [page, status] },
  )

  async function act(id: string, action: () => Promise<unknown>) {
    setBusyId(id)
    setError(null)
    try {
      await action()
      result.reload()
    } catch (cause) {
      setError(cause)
    } finally {
      setBusyId(null)
    }
  }

  const pendingCount = result.data?.items.filter((o) => o.can_respond).length ?? 0

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-stone-900">{t('nav.offers')}</h1>
        {pendingCount > 0 && <Badge tone="warning">{t('offer.awaitingYou')}</Badge>}
      </header>

      <Card>
        <div className="flex flex-wrap gap-2">
          {['', 'PENDING', 'ACCEPTED', 'REJECTED', 'COUNTERED', 'EXPIRED'].map((value) => (
            <button
              key={value || 'all'}
              type="button"
              onClick={() => {
                setStatus(value)
                setPage(1)
              }}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                status === value
                  ? 'bg-emerald-700 text-white'
                  : 'bg-white text-stone-700 ring-1 ring-stone-300 ring-inset hover:bg-stone-50'
              }`}
            >
              {value ? t(`status.${value}` as never) : t('app.all')}
            </button>
          ))}
        </div>
      </Card>

      {error ? <ErrorState error={error} /> : null}

      {result.initialLoading ? (
        <Loading />
      ) : result.error ? (
        <ErrorState error={result.error} onRetry={result.reload} />
      ) : !result.data || result.data.items.length === 0 ? (
        <Card>
          <EmptyState title={t('offer.noOffers')} hint={t('offer.noOffersHint')} />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={t('nav.offers')}
            columns={[
              t('offer.reference'),
              t('order.party.buyer'),
              t('order.party.seller'),
              t('offer.price'),
              t('offer.quantity'),
              t('status.label'),
              t('market.date'),
              '',
            ]}
          >
            {result.data.items.map((offer) => (
              <tr key={offer.id} className="hover:bg-stone-50">
                <td className="px-3 py-2">
                  <p className="font-medium whitespace-nowrap text-stone-900">
                    {offer.reference_code}
                  </p>
                  <p className="text-xs text-stone-500">{offer.lot_code ?? offer.lot_title}</p>
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  {offer.buyer_organisation ?? offer.buyer_name ?? '—'}
                  {offer.buyer_verified && (
                    <Badge tone="success">{t('offer.verifiedBuyer')}</Badge>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  {/* The party the caller is not; named for context. */}
                  {offer.is_buyer
                    ? (offer.lot_title ?? offer.lot_code ?? '—')
                    : (offer.buyer_organisation ?? offer.buyer_name ?? '—')}
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  {money(offer.offered_price)}
                  {offer.total_value !== null && (
                    <span className="block text-xs text-stone-500">
                      {t('offer.totalValue')}: {money(offer.total_value)}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                  {number(offer.quantity)} <UnitLabel unit={offer.unit} />
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={offer.status} tone={offerTone(offer.status)} domain="offer" />
                  {offer.status === 'COUNTERED' && (
                    <span className="block text-xs text-stone-500">
                      {t('offer.countered')}
                    </span>
                  )}
                  {offer.decline_reason && (
                    <span className="block text-xs text-red-700">
                      {t('offer.declineReason')}: {offer.decline_reason}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                  {relative(offer.created_at)}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap justify-end gap-1">
                    {offer.can_respond && offer.status === 'PENDING' && (
                      <>
                        <Button
                          size="sm"
                          busy={busyId === offer.id}
                          onClick={() => {
                            if (window.confirm(t('offer.acceptConfirm'))) {
                              void act(offer.id, () => offersApi.accept(offer.id))
                            }
                          }}
                        >
                          {t('offer.accept')}
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            const price = window.prompt(t('offer.counterPrice'))
                            if (price) {
                              void act(offer.id, () =>
                                offersApi.counter(offer.id, { offered_price: Number(price) }),
                              )
                            }
                          }}
                        >
                          {t('offer.counter')}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            const reason = window.prompt(t('offer.rejectReason'))
                            if (reason) {
                              void act(offer.id, () => offersApi.reject(offer.id, reason))
                            }
                          }}
                        >
                          {t('offer.reject')}
                        </Button>
                      </>
                    )}

                    {offer.is_buyer && offer.status === 'PENDING' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        busy={busyId === offer.id}
                        onClick={() => void act(offer.id, () => offersApi.withdraw(offer.id))}
                      >
                        {t('offer.withdraw')}
                      </Button>
                    )}

                    {offer.lot_id && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => navigate(`/lots/${offer.lot_id}`)}
                      >
                        {t('lot.detail')}
                      </Button>
                    )}
                  </div>
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
