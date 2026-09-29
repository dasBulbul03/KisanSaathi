/**
 * Browse lots (buyers) / my lots (farmers and FPOs).
 *
 * One component serves both because the list, filters and columns are
 * identical; only the query and the available actions differ. The backend
 * already scopes `/lots/mine` to the caller's own lots and hides other sellers'
 * drafts, so this screen never has to filter by ownership itself.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { useAsync } from '../hooks'
import { lots as lotsApi, markets } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Paginator,
  Table,
  cx,
  lotTone,
} from '../components/ui'
import { Button, Select, TextInput } from '../components/form'
import { GradeBadge, StatusBadge, UnitLabel } from '../components/labels'
import type { Commodity, FarmLot, Page } from '../lib/types'

export function LotsPage({ scope }: { scope: 'browse' | 'mine' }) {
  const { t, number, money } = useI18n()
  const navigate = useNavigate()
  const { hasRole, can } = useAuth()

  const [page, setPage] = useState(1)
  const [commodityId, setCommodityId] = useState('')
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')

  const commodityList = useAsync<Commodity[]>(async () => markets.commodities())

  const result = useAsync<Page<FarmLot>>(
    async () =>
      scope === 'mine'
        ? lotsApi.mine({ page })
        : lotsApi.list({
            page,
            ...(commodityId ? { commodity_id: commodityId } : {}),
            ...(status ? { status } : {}),
            ...(appliedSearch ? { search: appliedSearch } : {}),
          }),
    { deps: [scope, page, commodityId, status, appliedSearch] },
  )

  const isSeller = scope === 'mine'
  const canCreate = can('lot:create')

  function submitSearch(event: React.FormEvent) {
    event.preventDefault()
    setPage(1)
    setAppliedSearch(search.trim())
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-stone-900">
          {isSeller ? t('nav.lots') : t('nav.browseLots')}
        </h1>
        {isSeller && canCreate && (
          <Button onClick={() => navigate('/my-lots/new')}>{t('lot.new')}</Button>
        )}
      </header>

      {!isSeller && (
        <Card>
          <form onSubmit={submitSearch} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Select
              label={t('lot.commodity')}
              value={commodityId}
              onChange={(value) => {
                setCommodityId(value)
                setPage(1)
              }}
              options={(commodityList.data ?? []).map((commodity) => ({
                value: commodity.id,
                label: commodity.name,
              }))}
              placeholder={t('app.all')}
            />
            <Select
              label={t('lot.status')}
              value={status}
              onChange={(value) => {
                setStatus(value)
                setPage(1)
              }}
              options={['PUBLISHED', 'UNDER_OFFER', 'SOLD', 'IN_TRANSIT', 'COMPLETED'].map(
                (value) => ({ value, label: t(`status.${value}` as never) }),
              )}
              placeholder={t('app.all')}
            />
            <TextInput
              label={t('app.search')}
              value={search}
              onChange={setSearch}
              placeholder={t('lot.title')}
            />
            <div className="flex items-end gap-2">
              <Button type="submit" className="flex-1">
                {t('app.apply')}
              </Button>
              {(commodityId || status || appliedSearch) && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setCommodityId('')
                    setStatus('')
                    setSearch('')
                    setAppliedSearch('')
                    setPage(1)
                  }}
                >
                  {t('app.clear')}
                </Button>
              )}
            </div>
          </form>
        </Card>
      )}

      {result.initialLoading ? (
        <Loading />
      ) : result.error ? (
        <ErrorState error={result.error} onRetry={result.reload} />
      ) : !result.data || result.data.items.length === 0 ? (
        <Card>
          <EmptyState
            title={isSeller ? t('dash.noLots') : t('app.noResults')}
            hint={isSeller ? t('dash.noLotsHint') : t('app.noResultsHint')}
            action={
              isSeller && canCreate ? (
                <Button onClick={() => navigate('/my-lots/new')}>{t('dash.listLot')}</Button>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={isSeller ? t('nav.lots') : t('nav.browseLots')}
            columns={[
              t('lot.title'),
              t('lot.quantity'),
              t('lot.grade'),
              t('lot.expectedPrice'),
              t('lot.location'),
              t('lot.status'),
              t('offer.count'),
              '',
            ]}
          >
            {result.data.items.map((lot) => (
              <tr key={lot.id} className="cursor-pointer hover:bg-stone-50">
                <td className="px-3 py-2">
                  <p className="font-medium text-stone-900">{lot.title}</p>
                  <p className="text-xs text-stone-500">
                    {lot.lot_code} · {lot.commodity_name}
                    {lot.organic_certified && (
                      <span className="ml-1.5 text-emerald-700">· {t('lot.organic')}</span>
                    )}
                  </p>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                  {number(lot.available_quantity)} <UnitLabel unit={lot.unit} />
                </td>
                <td className="px-3 py-2">
                  <GradeBadge grade={lot.inspection_grade ?? lot.quality_grade} />
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  {lot.expected_price ? money(lot.expected_price) : '—'}
                </td>
                <td className="px-3 py-2 text-xs text-stone-600">
                  {[lot.village, lot.district].filter(Boolean).join(', ') || '—'}
                  {lot.distance_km !== null && lot.distance_km !== undefined && (
                    <span className="block text-stone-400">
                      {t('lot.kmAway', { km: number(lot.distance_km) })}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={lot.status} tone={lotTone(lot.status)} domain="lot" />
                </td>
                <td className="px-3 py-2 text-center text-stone-700">
                  {lot.active_offers_count ?? 0}
                </td>
                <td className="px-3 py-2 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => navigate(isSeller ? `/my-lots/${lot.id}` : `/lots/${lot.id}`)}
                  >
                    {t('app.viewAll')}
                  </Button>
                </td>
              </tr>
            ))}
          </Table>
          <div className="px-4">
            <Paginator meta={result.data.meta} onPage={setPage} />
          </div>
        </Card>
      )}

      {isSeller && result.data && result.data.items.length > 0 && hasRole('FARMER', 'FPO') && (
        <p className={cx('text-xs text-stone-400')}>{t('lot.publishHint')}</p>
      )}
    </div>
  )
}
