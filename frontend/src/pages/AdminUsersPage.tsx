/**
 * User administration.
 *
 * The two actions here — suspend and verify a buyer — are the ones that change
 * what an account can actually do, so both ask for a reason and both show the
 * backend's own error if refused. The UI does not second-guess the decision: the
 * backend owns the rules, this screen just reports what it says.
 */

import { useState } from 'react'

import { useAsync } from '../hooks'
import { admin } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Badge, Card, EmptyState, ErrorState, Loading, Paginator, Table, cx } from '../components/ui'
import { Button, Select, TextInput } from '../components/form'
import { RoleLabel, StatusBadge } from '../components/labels'
import type { Page, UserListItem, UserRole } from '../lib/types'

const ROLES: UserRole[] = [
  'FARMER',
  'FPO',
  'BUYER',
  'LOGISTICS_PARTNER',
  'QUALITY_INSPECTOR',
  'ADMIN',
]

export function AdminUsersPage() {
  const { t, number, date } = useI18n()
  const [page, setPage] = useState(1)
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [applied, setApplied] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)

  const counts = useAsync(async () => admin.userCounts())
  const list = useAsync<Page<UserListItem>>(
    async () =>
      admin.users({
        page,
        ...(role ? { role: role as UserRole } : {}),
        ...(status ? { status: status as never } : {}),
        ...(applied ? { search: applied } : {}),
      }),
    { deps: [page, role, status, applied] },
  )

  async function toggleSuspension(user: UserListItem) {
    const suspending = user.status === 'ACTIVE'
    const reason = window.prompt(
      suspending ? t('user.suspend') : t('user.activate'),
    )
    if (reason === null) return
    setBusyId(user.id)
    setActionError(null)
    try {
      await admin.setUserStatus(
        user.id,
        suspending ? 'SUSPENDED' : 'ACTIVE',
        reason || undefined,
      )
      list.reload()
    } catch (cause) {
      setActionError(cause)
    } finally {
      setBusyId(null)
    }
  }

  async function verify(user: UserListItem, approve: boolean) {
    const notes = window.prompt(
      approve ? t('user.verifyBuyer') : t('user.rejectBuyer'),
    )
    if (notes === null) return
    setBusyId(user.id)
    setActionError(null)
    try {
      await admin.verifyBuyer(user.id, { approve, ...(notes ? { notes } : {}) })
      list.reload()
    } catch (cause) {
      setActionError(cause)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-stone-900">{t('user.title')}</h1>

      <Card title={t('user.roleCounts')}>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              setRole('')
              setPage(1)
            }}
            className={cx(
              'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              !role
                ? 'bg-emerald-700 text-white'
                : 'bg-white text-stone-700 ring-1 ring-stone-300 ring-inset hover:bg-stone-50',
            )}
          >
            {t('app.all')}{' '}
            <span className="opacity-80">{number(counts.data?.total ?? 0)}</span>
          </button>
          {ROLES.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setRole(value)
                setPage(1)
              }}
              className={cx(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                role === value
                  ? 'bg-emerald-700 text-white'
                  : 'bg-white text-stone-700 ring-1 ring-stone-300 ring-inset hover:bg-stone-50',
              )}
            >
              <RoleLabel role={value} />{' '}
              <span className="opacity-80">{number(counts.data?.[value] ?? 0)}</span>
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <form
          className="grid gap-3 sm:grid-cols-3"
          onSubmit={(event) => {
            event.preventDefault()
            setPage(1)
            setApplied(search.trim())
          }}
        >
          <TextInput label={t('user.search')} value={search} onChange={setSearch} />
          <Select
            label={t('user.status')}
            value={status}
            onChange={(value) => {
              setStatus(value)
              setPage(1)
            }}
            placeholder={t('app.all')}
            options={['ACTIVE', 'PENDING', 'SUSPENDED', 'INACTIVE'].map((value) => ({
              value,
              label: t(`status.${value}` as never),
            }))}
          />
          <div className="flex items-end gap-2">
            <Button type="submit" className="flex-1">
              {t('app.search')}
            </Button>
            {(search || status || role) && (
              <Button
                variant="secondary"
                onClick={() => {
                  setSearch('')
                  setApplied('')
                  setStatus('')
                  setRole('')
                  setPage(1)
                }}
              >
                {t('app.clear')}
              </Button>
            )}
          </div>
        </form>
      </Card>

      {actionError ? <ErrorState error={actionError} /> : null}

      {list.initialLoading ? (
        <Loading />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={list.reload} />
      ) : !list.data || list.data.items.length === 0 ? (
        <Card>
          <EmptyState title={t('user.noUsers')} />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={t('user.title')}
            columns={[
              t('user.name'),
              t('user.role'),
              t('user.phone'),
              t('user.district'),
              t('user.status'),
              t('user.lastLogin'),
              '',
            ]}
          >
            {list.data.items.map((user) => (
              <tr key={user.id}>
                <td className="px-3 py-2">
                  <p className="font-medium text-stone-900">{user.full_name}</p>
                  {user.organisation_name && (
                    <p className="text-xs text-stone-500">{user.organisation_name}</p>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  <RoleLabel role={user.role} />
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-600">
                  {user.phone}
                </td>
                <td className="px-3 py-2 text-xs text-stone-600">{user.district ?? '—'}</td>
                <td className="px-3 py-2">
                  <StatusBadge value={user.status} />
                  {user.role === 'BUYER' && user.verification_status && (
                    <Badge tone={user.verification_status === 'VERIFIED' ? 'success' : 'warning'}>
                      {t(`status.${user.verification_status}` as never)}
                    </Badge>
                  )}
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                  {user.last_login_at ? date(user.last_login_at) : t('user.never')}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap justify-end gap-1">
                    {user.role === 'BUYER' && user.verification_status === 'PENDING' && (
                      <>
                        <Button size="sm" busy={busyId === user.id} onClick={() => void verify(user, true)}>
                          {t('user.verifyBuyer')}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void verify(user, false)}
                        >
                          {t('user.rejectBuyer')}
                        </Button>
                      </>
                    )}
                    <Button
                      size="sm"
                      variant={user.status === 'ACTIVE' ? 'ghost' : 'secondary'}
                      busy={busyId === user.id}
                      onClick={() => void toggleSuspension(user)}
                    >
                      {user.status === 'ACTIVE' ? t('user.suspend') : t('user.activate')}
                    </Button>
                  </div>
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
