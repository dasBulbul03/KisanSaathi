/**
 * Sign-in screen.
 *
 * The demo-account list is not decoration: the quickest way for anyone
 * reviewing this build to see all six roles is one tap per account. It is
 * hidden in production so the shipped app has no password on screen.
 */

import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { useAuth, DEFAULT_LANDING } from '../auth/AuthContext'
import { Button, TextInput } from '../components/form'
import { useI18n } from '../lib/i18n'
import { ApiError } from '../lib/api'
import { Card, ErrorState, cx } from '../components/ui'
import { RoleLabel } from '../components/labels'

interface DemoAccount {
  phone: string
  name: string
  role: string
}

const DEMO_ACCOUNTS: DemoAccount[] = [
  { phone: '9000000002', name: 'Ramesh Jadhav', role: 'FARMER' },
  { phone: '9000000003', name: 'Sunita Patil', role: 'FARMER' },
  { phone: '9000000004', name: 'Sahyadri FPO', role: 'FPO' },
  { phone: '9000000005', name: 'Anita Deshmukh', role: 'BUYER' },
  { phone: '9000000006', name: 'BulkMart Sourcing', role: 'BUYER' },
  { phone: '9000000007', name: 'Quality Inspector', role: 'QUALITY_INSPECTOR' },
  { phone: '9000000008', name: 'Sahyadri Logistics', role: 'LOGISTICS_PARTNER' },
  { phone: '9000000001', name: 'Platform Admin', role: 'ADMIN' },
]

const DEMO_PASSWORD = 'Demo@1234'

/**
 * The demo panel lists working credentials, so it is opt-in rather than
 * "hidden unless told not to show": an unset flag in a production build means
 * hidden. Development shows it unless explicitly disabled, because that is where
 * the seeded accounts are useful.
 */
const demoFlag = import.meta.env.VITE_SHOW_DEMO_ACCOUNTS
const showDemo =
  demoFlag === 'true' || (import.meta.env.DEV && demoFlag !== 'false')

export default function LoginPage() {
  const { signIn, profile } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()

  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  if (profile) return <Navigate to={DEFAULT_LANDING[profile.user.role]} replace />

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const next = await signIn(phone.trim(), password)
      navigate(DEFAULT_LANDING[next.user.role], { replace: true })
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 401
          ? new ApiError(401, null, t('auth.credentialsRejected'))
          : cause,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-stone-50 lg:flex-row">
      <div className="flex flex-1 items-center justify-center p-4 lg:p-8">
        <div className="w-full max-w-sm">
          <div className="mb-6 text-center">
            <p className="text-3xl" aria-hidden>
              🌾
            </p>
            <h1 className="mt-2 text-2xl font-semibold text-stone-900">{t('app.name')}</h1>
            <p className="text-sm text-stone-500">{t('app.tagline')}</p>
          </div>

          <Card>
            <form onSubmit={handleSubmit} className="space-y-4">
              <TextInput
                label={t('auth.phone')}
                value={phone}
                onChange={setPhone}
                type="tel"
                inputMode="numeric"
                autoComplete="username"
                maxLength={10}
                required
                hint={t('auth.phoneHint')}
              />
              <TextInput
                label={t('auth.password')}
                value={password}
                onChange={setPassword}
                type="password"
                autoComplete="current-password"
                required
              />

              {error ? <ErrorState error={error} /> : null}

              <Button type="submit" busy={busy} className="w-full">
                {busy ? t('auth.signingIn') : t('auth.signIn')}
              </Button>
            </form>

            <p className="mt-4 text-center text-sm text-stone-600">
              {t('auth.needAccount')}{' '}
              <Link to="/register" className="font-medium text-emerald-700 hover:underline">
                {t('auth.register')}
              </Link>
            </p>
          </Card>
        </div>
      </div>

      {showDemo && (
        <aside className="border-t border-stone-200 bg-white p-4 lg:w-96 lg:border-t-0 lg:border-l lg:p-8">
          <h2 className="text-sm font-semibold text-stone-900">{t('auth.demoAccounts')}</h2>
          <p className="mt-0.5 text-xs text-stone-500">{t('auth.demoHint')}</p>
          <ul className="mt-3 space-y-1.5">
            {DEMO_ACCOUNTS.map((account) => (
              <li key={account.phone}>
                <button
                  type="button"
                  onClick={() => {
                    setPhone(account.phone)
                    setPassword(DEMO_PASSWORD)
                    setError(null)
                  }}
                  className={cx(
                    'w-full rounded-lg border border-stone-200 px-3 py-2 text-left transition-colors',
                    'hover:border-emerald-600 hover:bg-emerald-50',
                    phone === account.phone && 'border-emerald-600 bg-emerald-50',
                  )}
                >
                  <span className="block text-sm font-medium text-stone-800">
                    {account.name}
                  </span>
                  <span className="block text-xs text-stone-500">
                    {account.phone} · <RoleLabel role={account.role} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
      )}
    </div>
  )
}
