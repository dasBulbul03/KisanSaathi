/**
 * The signed-in shell: header, sidebar, notifications badge, language toggle.
 *
 * The sidebar collapses to a drawer under `lg`. The header carries the three
 * things that must be reachable from anywhere: the language toggle (so a farmer
 * can read the whole app in Marathi without navigating), the notification badge,
 * and sign-out.
 */

import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { cx, ErrorState, Loading } from './ui'
import { useI18n } from '../lib/i18n'
import { useEscapeKey, useMediaQuery, useNav } from '../hooks'
import { RoleLabel } from './labels'
import type { TranslationKey } from '../lib/dictionaries'

function LanguageToggle() {
  const { language, setLanguage, t } = useI18n()
  return (
    <div
      className="inline-flex overflow-hidden rounded-md border border-stone-300 text-xs font-medium"
      role="group"
      aria-label={t('nav.menu')}
    >
      {(
        [
          { code: 'en', label: 'English', short: 'EN' },
          { code: 'mr', label: 'मराठी', short: 'मराठी' },
        ] as const
      ).map((option) => (
        <button
          key={option.code}
          type="button"
          onClick={() => setLanguage(option.code)}
          aria-pressed={language === option.code}
          title={option.label}
          className={cx(
            'px-2.5 py-1.5 transition-colors',
            language === option.code
              ? 'bg-emerald-700 text-white'
              : 'bg-white text-stone-700 hover:bg-stone-100',
          )}
        >
          {option.short}
        </button>
      ))}
    </div>
  )
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useI18n()
  const { groups } = useNav()
  return (
    <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4" aria-label={t('nav.menu')}>
      {groups.map((group) => (
        <div key={group.headingKey}>
          <p className="px-2 pb-1.5 text-xs font-semibold tracking-wide text-stone-400 uppercase">
            {t(group.headingKey)}
          </p>
          <ul className="space-y-0.5">
            {group.items.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cx(
                      'block rounded-md px-2.5 py-2 text-sm transition-colors',
                      isActive
                        ? 'bg-emerald-50 font-medium text-emerald-800'
                        : 'text-stone-700 hover:bg-stone-100',
                    )
                  }
                >
                  {t(item.labelKey as TranslationKey)}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}

export default function AppLayout({ unreadCount }: { unreadCount: number }) {
  const { profile, role, signOut } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()
  const isDesktop = useMediaQuery('(min-width: 1024px)')
  const [drawerOpen, setDrawerOpen] = useState(false)

  useEscapeKey(drawerOpen, () => setDrawerOpen(false))

  // Close the drawer on navigation so a tap on a link does not leave it open
  // behind the new screen on a phone. Adjusting state during render, rather than
  // in an effect, means the closed drawer is part of the same paint as the new
  // screen instead of a frame later.
  const [drawerPath, setDrawerPath] = useState(location.pathname)
  if (drawerPath !== location.pathname) {
    setDrawerPath(location.pathname)
    setDrawerOpen(false)
  }

  useEffect(() => {
    // Keeps the browser tab title honest about pending work.
    document.title = unreadCount > 0 ? `(${unreadCount}) KisanSaathi` : 'KisanSaathi'
  }, [unreadCount])

  async function handleSignOut() {
    await signOut()
    navigate('/login', { replace: true })
  }

  if (!profile || !role) return <Loading />

  const sidebar = (
    <>
      <div className="flex h-14 items-center gap-2 border-b border-stone-200 px-4">
        <span aria-hidden className="text-xl">
          🌾
        </span>
        <div>
          <p className="text-sm font-semibold text-stone-900">{t('app.name')}</p>
        </div>
      </div>
      <NavLinks onNavigate={() => setDrawerOpen(false)} />
      <div className="border-t border-stone-200 p-3">
        <p className="truncate text-sm font-medium text-stone-800">
          {profile.user.full_name}
        </p>
        <p className="truncate text-xs text-stone-500">
          <RoleLabel role={role} />
        </p>
      </div>
    </>
  )

  return (
    <div className="min-h-dvh bg-stone-50">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-stone-200 bg-white px-4">
        {!isDesktop && (
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="rounded-md p-1.5 text-stone-700 hover:bg-stone-100"
            aria-label={t('nav.menu')}
            aria-expanded={drawerOpen}
          >
            <span aria-hidden>☰</span>
          </button>
        )}

        <span className="font-semibold text-stone-900 lg:hidden">{t('app.name')}</span>
        <p className="hidden text-sm text-stone-500 lg:block">{t('app.tagline')}</p>

        <div className="ml-auto flex items-center gap-2">
          <LanguageToggle />

          <button
            type="button"
            onClick={() => navigate('/notifications')}
            className="relative rounded-md p-1.5 text-stone-700 hover:bg-stone-100"
            aria-label={
              unreadCount
                ? t('notification.unread', { count: unreadCount })
                : t('notification.title')
            }
          >
            <span aria-hidden>🔔</span>
            {unreadCount > 0 ? (
              <span className="absolute -top-0.5 -right-0.5 flex size-4 items-center justify-center rounded-full bg-red-600 text-[10px] font-semibold text-white">
                {unreadCount > 9 ? '9+' : unreadCount}
              </span>
            ) : null}
          </button>

          <button
            type="button"
            onClick={() => void handleSignOut()}
            className="rounded-md px-2.5 py-1.5 text-sm text-stone-700 hover:bg-stone-100"
          >
            {t('auth.signOut')}
          </button>
        </div>
      </header>

      <div className="lg:flex">
        {isDesktop ? (
          <aside className="sticky top-14 flex h-[calc(100dvh-3.5rem)] w-60 shrink-0 flex-col border-r border-stone-200 bg-white">
            {sidebar}
          </aside>
        ) : (
          drawerOpen && (
            <div className="fixed inset-0 z-40 lg:hidden">
              <div
                className="absolute inset-0 bg-stone-900/40"
                onClick={() => setDrawerOpen(false)}
                aria-hidden
              />
              <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-white shadow-xl">
                {sidebar}
              </aside>
            </div>
          )
        )}

        <main className="min-w-0 flex-1 p-4 lg:p-6">
          <Outlet />
        </main>
      </div>

    </div>
  )
}

/** Wraps a screen that failed to load, so every page handles errors the same. */
export function PageError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return <ErrorState error={error} onRetry={onRetry} />
}
