/**
 * Admin dashboard.
 *
 * The "needs your attention" panel is the reason this screen exists: it turns
 * four separate queues into one list of counts, and each count links straight to
 * the screen that clears it. An admin who has to remember four places to look
 * will eventually miss one.
 */

import { useNavigate } from 'react-router-dom'

import { useAsync } from '../hooks'
import { admin, dashboards } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Card, ErrorState, Loading, StatGrid, Table, cx } from '../components/ui'
import { Button } from '../components/form'
import { RoleLabel } from '../components/labels'
import { DemoBanner, StatTile } from '../components/dashboardParts'
import type { AdminDashboard } from '../lib/types'

interface Queue {
  label: string
  value: number
  to: string
}

export default function AdminDashboardPage() {
  const { t, number, moneyCompact, money } = useI18n()
  const navigate = useNavigate()

  const state = useAsync<AdminDashboard>(async () => dashboards.admin())

  if (state.initialLoading) return <Loading />
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />
  const data = state.data
  if (!data) return null

  const pending = data.pending_actions
  const queues: Queue[] = [
    { label: t('dash.admin.openGrievances'), value: pending.open_grievances, to: '/grievances' },
    { label: t('dash.admin.logistics'), value: pending.unassigned_logistics, to: '/logistics' },
    { label: t('dash.admin.inspections'), value: pending.pending_inspections, to: '/inspections' },
    { label: t('dash.admin.buyers'), value: pending.pending_buyers, to: '/admin' },
  ]
  const openQueues = queues.filter((queue) => queue.value > 0)

  return (
    <div className="space-y-5">
      {data.is_demo_data && <DemoBanner />}

      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">{t('dash.greeting.admin')}</h1>
          <p className="text-sm text-stone-500">{t('app.tagline')}</p>
        </div>
        <Button variant="secondary" size="sm" onClick={state.reload}>
          {t('app.retry')}
        </Button>
      </header>

      <StatGrid>
        <StatTile
          label={t('dash.admin.users')}
          value={number(data.registrations.active_users)}
          hint={`+${number(data.registrations.new_last_30_days)} / 30d`}
        />
        <StatTile
          label={t('dash.admin.trade30')}
          value={moneyCompact(data.trade.trade_value_30d)}
        />
        <StatTile
          label={t('dash.admin.completed')}
          value={number(data.trade.completed_orders)}
        />
        <StatTile
          label={t('dash.admin.pending')}
          value={number(data.trade.pending_orders)}
          tone={data.trade.pending_orders > 0 ? 'warning' : 'default'}
        />
      </StatGrid>

      <Card title={t('dash.admin.pendingActions')}>
        {openQueues.length === 0 ? (
          <p className="py-4 text-center text-sm text-stone-500">{t('dash.admin.noPending')}</p>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {openQueues.map((queue) => (
              <li key={queue.to}>
                <button
                  type="button"
                  onClick={() => navigate(queue.to)}
                  className="w-full rounded-lg border border-amber-300 bg-amber-50 p-3 text-left transition-colors hover:border-amber-400 hover:bg-amber-100"
                >
                  <span className="block text-2xl font-semibold text-amber-900">
                    {number(queue.value)}
                  </span>
                  <span className="block text-xs text-amber-800">{queue.label}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={t('dash.admin.byRole')} padded={false}>
          <Table caption={t('dash.admin.byRole')} columns={[t('user.role'), t('dash.admin.users')]}>
            {Object.entries(data.registrations.by_role).map(([role, count]) => (
              <tr key={role}>
                <td className="px-3 py-2 text-stone-800">
                  <RoleLabel role={role} />
                </td>
                <td className="px-3 py-2 text-right font-medium text-stone-900">
                  {number(count)}
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title={t('dash.admin.demandByCommodity')} padded={false}>
          {data.demand_by_commodity.length === 0 ? (
            <p className="p-4 text-sm text-stone-500">{t('app.noResults')}</p>
          ) : (
            <Table
              caption={t('dash.admin.demandByCommodity')}
              columns={[
                t('lot.commodity'),
                t('dash.admin.openDemands'),
                t('demand.required'),
                t('dash.admin.activeLots'),
              ]}
            >
              {data.demand_by_commodity.map((row) => (
                <tr key={row.commodity_id}>
                  <td className="px-3 py-2 text-stone-800">{row.commodity_name}</td>
                  <td className="px-3 py-2 text-right text-stone-700">
                    {number(row.open_demands)}
                  </td>
                  <td className="px-3 py-2 text-right text-stone-700">
                    {number(row.demanded_quintal)}
                  </td>
                  <td className="px-3 py-2 text-right text-stone-700">
                    {number(row.active_lots)}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={t('dash.admin.byDistrict')} padded={false}>
          <Table
            caption={t('dash.admin.byDistrict')}
            columns={[
              t('user.district'),
              t('dash.admin.users'),
              t('dash.admin.activeLots'),
              t('dash.admin.tradeValue'),
            ]}
          >
            {data.activity_by_district.map((row) => (
              <tr key={row.district}>
                <td className="px-3 py-2 text-stone-800">{row.district}</td>
                <td className="px-3 py-2 text-right text-stone-700">{number(row.users)}</td>
                <td className="px-3 py-2 text-right text-stone-700">
                  {number(row.active_lots)}
                </td>
                <td className="px-3 py-2 text-right text-stone-700">
                  {money(row.trade_value)}
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title={t('dash.admin.systemHealth')}>
          <dl className="space-y-2 text-sm">
            <Row label={t('app.name')} value={data.system_health.database} />
            <Row
              label={t('lot.commodity')}
              value={number(data.system_health.commodities)}
            />
            <Row label={t('user.district')} value={number(data.system_health.districts)} />
            <Row
              label={t('market.dataSource')}
              value={
                <span
                  className={cx(
                    'font-medium',
                    data.system_health.demo_price_data ? 'text-amber-700' : 'text-emerald-700',
                  )}
                >
                  {data.system_health.demo_price_data
                    ? t('app.demoBanner')
                    : t('market.dataSource')}
                </span>
              }
            />
            <Row
              label={t('dash.admin.trade90')}
              value={money(data.trade.trade_value_90d)}
            />
          </dl>
        </Card>
      </div>

      <Card
        title={t('user.title')}
        action={
          <Button onClick={() => navigate('/admin')}>{t('app.viewAll')}</Button>
        }
        padded={false}
      >
        <UserPreview />
      </Card>
    </div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-stone-100 pb-2 last:border-0">
      <dt className="text-stone-500">{label}</dt>
      <dd className="text-right font-medium text-stone-900">{value}</dd>
    </div>
  )
}

/** The five most recent registrations, so a new signup is visible at a glance. */
function UserPreview() {
  const { t } = useI18n()
  const state = useAsync(async () => admin.users({ page: 1, page_size: 5 }))

  if (state.initialLoading) return <Loading />
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />
  if (!state.data) return null

  return (
    <Table
      caption={t('user.title')}
      columns={[t('user.name'), t('user.role'), t('user.district'), t('user.joined')]}
    >
      {state.data.items.map((user) => (
        <tr key={user.id}>
          <td className="px-3 py-2 text-stone-800">{user.full_name}</td>
          <td className="px-3 py-2 text-stone-700">
            <RoleLabel role={user.role} />
          </td>
          <td className="px-3 py-2 text-stone-700">{user.district ?? '—'}</td>
          <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
            {user.created_at.slice(0, 10)}
          </td>
        </tr>
      ))}
    </Table>
  )
}
