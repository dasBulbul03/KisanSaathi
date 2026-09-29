/**
 * Auth state: the signed-in profile, sign-in/sign-out, and the routing helper
 * that sends each role to the screen it can actually use.
 *
 * The profile is re-fetched on mount rather than trusted from storage, so a
 * suspended user's account stops working immediately instead of at token expiry.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError, clearTokens, isSignedIn, setSessionLostHandler } from '../lib/api'
import { auth as authApi } from '../lib/endpoints'
import type { Profile, UserRole } from '../lib/types'

export const HOME_FOR_ROLE: Record<UserRole, string> = {
  FARMER: '/dashboard',
  FPO: '/dashboard',
  BUYER: '/dashboard',
  ADMIN: '/admin',
  LOGISTICS_PARTNER: '/logistics',
  QUALITY_INSPECTOR: '/inspections',
}

/**
 * Inspector and logistics have no personal dashboard, so the backend answers
 * `/dashboards/me` with 403 for them. They are sent to their working queue
 * rather than shown an error.
 */
export const DEFAULT_LANDING: Record<UserRole, string> = {
  ...HOME_FOR_ROLE,
  LOGISTICS_PARTNER: '/logistics',
  QUALITY_INSPECTOR: '/inspections',
}

interface AuthValue {
  profile: Profile | null
  role: UserRole | null
  loading: boolean
  error: string | null
  signIn: (phone: string, password: string) => Promise<Profile>
  signUp: (body: Record<string, unknown>) => Promise<Profile>
  signOut: () => Promise<void>
  refreshProfile: () => Promise<void>
  can: (permission: string) => boolean
  hasRole: (...roles: UserRole[]) => boolean
  /** True when the signed-in role has a dashboard; drives route guards. */
  hasDashboard: boolean
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [error, setError] = useState<string | null>(null)
  // No token in storage means there is nothing to confirm, so the app is ready
  // immediately. Initialising rather than clearing in an effect avoids a render
  // that briefly shows a loading state the signed-out visitor never needed.
  const [sessionChecked, setSessionChecked] = useState(!isSignedIn())

  const refreshProfile = useCallback(async () => {
    try {
      setProfile(await authApi.me())
      setError(null)
    } catch (cause) {
      setProfile(null)
      // A signed-out visitor is not an error worth showing.
      if (cause instanceof ApiError && cause.status === 401) {
        clearTokens()
        setError(null)
      } else {
        setError(cause instanceof Error ? cause.message : 'unknown')
      }
    }
  }, [])

  useEffect(() => {
    // A token in storage means the app was reloaded mid-session; confirm it.
    if (!isSignedIn()) return
    let active = true
    void (async () => {
      await refreshProfile()
      if (active) setSessionChecked(true)
    })()
    return () => {
      active = false
    }
  }, [refreshProfile])

  useEffect(() => {
    // The API client tells us when a refresh failed and the session is gone.
    setSessionLostHandler(() => setProfile(null))
    return () => setSessionLostHandler(null)
  }, [])

  const signIn = useCallback(async (phone: string, password: string) => {
    await authApi.login(phone, password)
    const next = await authApi.me()
    setProfile(next)
    setError(null)
    return next
  }, [])

  const signUp = useCallback(async (body: Record<string, unknown>) => {
    const next = await authApi.register(body)
    // Registration does not sign the user in, so they sign in after this.
    return next
  }, [])

  const signOut = useCallback(async () => {
    await authApi.logout()
    setProfile(null)
  }, [])

  const value = useMemo<AuthValue>(() => {
    const permissions = new Set(profile?.permissions ?? [])
    const role = profile?.user.role ?? null
    return {
      profile,
      role,
      loading: !sessionChecked,
      error,
      signIn,
      signUp,
      signOut,
      refreshProfile,
      can: (permission) => permissions.has(permission),
      hasRole: (...roles) => (role ? roles.includes(role) : false),
      hasDashboard:
        role === 'FARMER' || role === 'FPO' || role === 'BUYER' || role === 'ADMIN',
    }
  }, [profile, sessionChecked, error, signIn, signUp, signOut, refreshProfile])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
