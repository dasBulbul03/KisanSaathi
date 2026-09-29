/**
 * Registration.
 *
 * Only farmer, FPO and buyer self-register. Inspector, logistics and admin
 * accounts are staff-created, so those roles are not offered here; the backend
 * rejects them regardless, and hiding them avoids an error on submit.
 *
 * The role choice drives the conditional fields, because a buyer needs an
 * organisation and a farmer needs a village, and neither is meaningful for the
 * other.
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { Button, Checkbox, Select, TextInput } from '../components/form'
import { useI18n } from '../lib/i18n'
import { ApiError } from '../lib/api'
import { Card, ErrorState } from '../components/ui'
import { useRoleLabel } from '../components/labels'

const SELF_SERVICE_ROLES = ['FARMER', 'FPO', 'BUYER'] as const

const BUYER_TYPES = [
  { value: 'RETAILER', label: 'Retailer' },
  { value: 'WHOLESALER', label: 'Wholesaler' },
  { value: 'PROCESSOR', label: 'Processor' },
  { value: 'EXPORT_TRADER', label: 'Export trader' },
  { value: 'INSTITUTION', label: 'Institution' },
]

export default function RegisterPage() {
  const { signUp, signIn } = useAuth()
  const { t } = useI18n()
  const roleLabel = useRoleLabel()
  const navigate = useNavigate()

  const [role, setRole] = useState<string>('FARMER')
  const [fullName, setFullName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [district, setDistrict] = useState('')
  const [village, setVillage] = useState('')
  const [organisation, setOrganisation] = useState('')
  const [buyerType, setBuyerType] = useState('RETAILER')
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  function validate(): string | null {
    if (!/^[6-9]\d{9}$/.test(phone.trim())) return t('form.invalidPhone')
    if (password.length < 8) return t('form.invalidPassword')
    if (password !== confirm) return t('form.passwordMismatch')
    if (!accepted) return t('form.required')
    return null
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const problem = validate()
    if (problem) {
      setError(new ApiError(422, null, problem))
      return
    }

    setBusy(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        full_name: fullName.trim(),
        phone: phone.trim(),
        password,
        role,
        district: district.trim() || undefined,
      }
      if (email.trim()) body.email = email.trim()
      if (role === 'FARMER' && village.trim()) body.village = village.trim()
      if (role !== 'FARMER' && organisation.trim()) {
        body.organisation_name = organisation.trim()
      }
      if (role === 'BUYER') body.buyer_type = buyerType

      await signUp(body)
      // Registering does not sign you in; do it immediately so the new account
      // lands on its dashboard instead of back at this form.
      await signIn(phone.trim(), password)
      navigate('/dashboard', { replace: true })
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-stone-50 p-4">
      <div className="w-full max-w-md">
        <div className="mb-5 text-center">
          <p className="text-3xl" aria-hidden>
            🌾
          </p>
          <h1 className="mt-2 text-xl font-semibold text-stone-900">{t('auth.register')}</h1>
        </div>

        <Card>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Select
              label={t('auth.role')}
              value={role}
              onChange={setRole}
              options={SELF_SERVICE_ROLES.map((value) => ({
                value,
                label: roleLabel(value),
              }))}
            />

            <TextInput
              label={t('auth.fullName')}
              value={fullName}
              onChange={setFullName}
              required
              autoComplete="name"
            />
            <TextInput
              label={t('auth.phone')}
              value={phone}
              onChange={setPhone}
              type="tel"
              inputMode="numeric"
              maxLength={10}
              required
              autoComplete="username"
            />
            <TextInput
              label={t('auth.email')}
              value={email}
              onChange={setEmail}
              type="email"
              autoComplete="email"
            />
            <TextInput
              label={t('auth.district')}
              value={district}
              onChange={setDistrict}
            />

            {role === 'FARMER' ? (
              <TextInput label={t('lot.village')} value={village} onChange={setVillage} />
            ) : (
              <TextInput
                label={t('profile.organisation')}
                value={organisation}
                onChange={setOrganisation}
                required
              />
            )}

            {role === 'BUYER' && (
              <Select
                label={t('demand.title')}
                value={buyerType}
                onChange={setBuyerType}
                options={BUYER_TYPES}
              />
            )}

            <TextInput
              label={t('auth.password')}
              value={password}
              onChange={setPassword}
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

            <Checkbox
              label={t('auth.register')}
              checked={accepted}
              onChange={setAccepted}
            />

            {error ? <ErrorState error={error} /> : null}

            <Button type="submit" busy={busy} className="w-full">
              {busy ? t('auth.registering') : t('auth.register')}
            </Button>
          </form>

          <p className="mt-4 text-center text-sm text-stone-600">
            {t('auth.haveAccount')}{' '}
            <Link to="/login" className="font-medium text-emerald-700 hover:underline">
              {t('auth.signIn')}
            </Link>
          </p>
        </Card>
      </div>
    </div>
  )
}
