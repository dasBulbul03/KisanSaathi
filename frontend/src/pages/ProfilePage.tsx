/**
 * Profile and password change.
 *
 * Role-specific detail is rendered from whichever of `farmer`, `fpo` or `buyer`
 * the backend populated, rather than by branching on the role. That keeps the
 * screen correct if a role ever carries more than one of those profiles.
 */

import { useState } from 'react'

import { useAuth } from '../auth/AuthContext'
import { useAsync } from '../hooks'
import { auth as authApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Badge, Card, ErrorState } from '../components/ui'
import { Button, TextInput } from '../components/form'
import { RoleLabel } from '../components/labels'

export function ProfilePage() {
  const { profile } = useAuth()
  const { t, number } = useI18n()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [done, setDone] = useState(false)

  const details = useAsync(async () => authApi.me())

  if (!profile) return null
  const { user, farmer, fpo, buyer } = details.data ?? profile

  async function changePassword(event: React.FormEvent) {
    event.preventDefault()
    if (next !== confirm) {
      setError(new Error(t('form.passwordMismatch')))
      return
    }
    setBusy(true)
    setError(null)
    setDone(false)
    try {
      await authApi.changePassword(current, next)
      setDone(true)
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold text-stone-900">{t('profile.title')}</h1>

      <Card>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-lg font-medium text-stone-900">{user.full_name}</p>
            <p className="text-sm text-stone-500">
              <RoleLabel role={user.role} />
            </p>
          </div>
          <StatusPill status={user.status} />
        </div>

        <dl className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2">
          <Field label={t('profile.phone')} value={user.phone} />
          <Field label={t('profile.email')} value={user.email ?? '—'} />
          <Field label={t('user.district')} value={user.district ?? '—'} />
          <Field label={t('auth.state')} value={user.state ?? '—'} />
        </dl>
      </Card>

      {farmer && (
        <Card title={t('role.FARMER')}>
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            <Field label={t('profile.farmerId')} value={farmer.farmer_id_code ?? '—'} />
            <Field
              label={t('lot.village')}
              value={[farmer.village, farmer.taluka].filter(Boolean).join(', ') || '—'}
            />
            <Field
              label={t('profile.farmArea')}
              value={farmer.farm_area_acres ? `${number(farmer.farm_area_acres)} ${t('profile.acres')}` : '—'}
            />
            <Field
              label={t('storage.capacity')}
              value={farmer.storage_capacity_quintal ? number(farmer.storage_capacity_quintal) : '—'}
            />
            <Field label={t('profile.upi')} value={farmer.upi_id ?? '—'} />
            <Field label={t('profile.bank')} value={farmer.bank_name ?? '—'} />
            <Field label={t('profile.ifsc')} value={farmer.ifsc_code ?? '—'} />
            <Field label={t('profile.kcc')} value={farmer.kcc_number ?? '—'} />
          </dl>
        </Card>
      )}

      {fpo && (
        <Card title={t('role.FPO')}>
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            <Field label={t('profile.organisation')} value={fpo.organisation_name} />
            <Field label={t('profile.members')} value={number(fpo.member_count)} />
            <Field
              label={t('profile.womenMembers')}
              value={number(fpo.women_member_count)}
            />
            <Field
              label={t('storage.capacity')}
              value={number(fpo.aggregate_capacity_quintal)}
            />
            <Field label={t('profile.phone')} value={fpo.contact_phone ?? '—'} />
            <Field label={t('profile.title')} value={fpo.contact_person ?? '—'} />
          </dl>
        </Card>
      )}

      {buyer && (
        <Card title={t('role.BUYER')}>
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            <Field label={t('profile.organisation')} value={buyer.organisation_name} />
            <Field
              label={t('status.label')}
              value={
                <Badge tone={buyer.verification_status === 'VERIFIED' ? 'success' : 'warning'}>
                  {t(`status.${buyer.verification_status}` as never)}
                </Badge>
              }
            />
            <Field label={t('profile.gst')} value={buyer.gst_number ?? '—'} />
            <Field label={t('profile.fssai')} value={buyer.fssai_licence ?? '—'} />
            <Field label={t('user.district')} value={buyer.district ?? '—'} />
            <Field
              label={t('demand.required')}
              value={buyer.monthly_volume_quintal ? number(buyer.monthly_volume_quintal) : '—'}
            />
          </dl>
          {buyer.verification_notes && (
            <p className="mt-3 rounded-md bg-stone-50 p-3 text-sm text-stone-700">
              {buyer.verification_notes}
            </p>
          )}
        </Card>
      )}

      <Card title={t('profile.changePassword')}>
        <form onSubmit={changePassword} className="space-y-3">
          <TextInput
            label={t('profile.currentPassword')}
            value={current}
            onChange={setCurrent}
            type="password"
            autoComplete="current-password"
            required
          />
          <TextInput
            label={t('profile.newPassword')}
            value={next}
            onChange={setNext}
            type="password"
            autoComplete="new-password"
            required
            hint={t('auth.passwordHint')}
          />
          <TextInput
            label={t('auth.confirmPassword')}
            value={confirm}
            onChange={setConfirm}
            type="password"
            autoComplete="new-password"
            required
          />
          {error ? <ErrorState error={error} /> : null}
          {done && (
            <p className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
              {t('profile.passwordChanged')}
            </p>
          )}
          <Button type="submit" busy={busy}>
            {t('profile.changePassword')}
          </Button>
        </form>
      </Card>
    </div>
  )
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-stone-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-stone-900">{value}</dd>
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const { t } = useI18n()
  return (
    <Badge tone={status === 'ACTIVE' ? 'success' : status === 'SUSPENDED' ? 'danger' : 'neutral'}>
      {t(`status.${status}` as never)}
    </Badge>
  )
}
