/**
 * Storage facilities.
 *
 * Two views: a buyer's search for somewhere to put produce, and a seller's own
 * facilities with capacity they can publish. `available_quintal` is computed
 * server-side from `capacity - occupied`, so the UI never does that arithmetic
 * itself and cannot disagree with the backend.
 */

import { useAuth } from '../auth/AuthContext'
import { useAsync } from '../hooks'
import { storage as storageApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Badge, Card, EmptyState, ErrorState, Loading, Table, cx } from '../components/ui'
import { StorageTypeLabel, UnitLabel } from '../components/labels'
import type { Page, StorageFacility } from '../lib/types'

export function StoragePage({ scope }: { scope: 'options' | 'mine' }) {
  const { t, number, money } = useI18n()
  const { can } = useAuth()
  const isMine = scope === 'mine'

  const options = useAsync<StorageFacility[]>(
    async () => storageApi.options(),
    { enabled: !isMine },
  )
  const mine = useAsync<Page<StorageFacility>>(
    async () => storageApi.mine({ page_size: 50 }),
    { enabled: isMine },
  )

  const source = isMine ? mine : options
  const items = isMine
    ? (mine.data?.items ?? [])
    : (options.data ?? [])

  const capacity = items.reduce((sum, f) => sum + (f.capacity_quintal ?? 0), 0)
  const available = items.reduce((sum, f) => sum + (f.available_quintal ?? 0), 0)

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-stone-900">
        {isMine ? t('storage.myFacilities') : t('storage.find')}
      </h1>

      {isMine && items.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-stone-200 bg-white p-3">
            <p className="text-xs text-stone-500">{t('storage.capacity')}</p>
            <p className="mt-1 text-xl font-semibold text-stone-900">{number(capacity)}</p>
          </div>
          <div className="rounded-lg border border-stone-200 bg-white p-3">
            <p className="text-xs text-stone-500">{t('storage.available')}</p>
            <p className="mt-1 text-xl font-semibold text-emerald-700">{number(available)}</p>
          </div>
        </div>
      )}

      {source.initialLoading ? (
        <Loading />
      ) : source.error ? (
        <ErrorState error={source.error} onRetry={source.reload} />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            title={t('app.noResults')}
            hint={isMine ? t('app.noResultsHint') : undefined}
            action={
              isMine && can('storage:manage_own') ? (
                <span className="text-xs text-stone-500">{t('storage.add')}</span>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={t('storage.title')}
            columns={[
              t('storage.name'),
              t('storage.type'),
              t('storage.capacity'),
              t('storage.available'),
              t('lot.location'),
              t('storage.cost'),
              '',
            ]}
          >
            {items.map((facility) => (
              <tr key={facility.id}>
                <td className="px-3 py-2">
                  <p className="font-medium text-stone-900">{facility.name}</p>
                  {facility.is_private && (
                    <Badge tone="neutral">{t('storage.private')}</Badge>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  <StorageTypeLabel type={facility.storage_type} />
                  {facility.temperature_controlled && (
                    <Badge tone="info">{t('storage.coldChain')}</Badge>
                  )}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-stone-700">
                  {number(facility.capacity_quintal)} <UnitLabel unit="quintal" />
                </td>
                <td
                  className={cx(
                    'px-3 py-2 font-medium whitespace-nowrap',
                    (facility.available_quintal ?? 0) > 0 ? 'text-emerald-700' : 'text-stone-400',
                  )}
                >
                  {number(facility.available_quintal)} <UnitLabel unit="quintal" />
                </td>
                <td className="px-3 py-2 text-xs text-stone-600">
                  {[facility.village, facility.district].filter(Boolean).join(', ') || '—'}
                  {facility.distance_km !== null && (
                    <span className="block text-stone-400">
                      {t('lot.kmAway', { km: number(facility.distance_km) })}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-700">
                  {facility.storage_cost_per_quintal_month
                    ? money(facility.storage_cost_per_quintal_month)
                    : '—'}
                </td>
                <td className="px-3 py-2 text-xs text-stone-600">
                  {facility.contact_phone ?? facility.contact_person ?? '—'}
                </td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </div>
  )
}
