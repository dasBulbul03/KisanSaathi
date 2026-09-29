/**
 * Data fetching and role-aware navigation.
 *
 * The rules here came out of the backend's actual behaviour rather than
 * convenience:
 *
 * - `can()` reads the permission list the backend sends in `/auth/me`. The UI
 *   hides what a role cannot do, but the backend still enforces every check, so
 *   a hidden button is a courtesy rather than a security boundary.
 * - Nav is filtered by permission, not hard-coded per role, so a permission
 *   change in `rbac.py` needs no frontend edit.
 * - The two roles with no dashboard land on their own queue rather than an error.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react'
import type { ReactNode } from 'react'

import { ApiError } from '../lib/api'
import type { TranslationKey } from '../lib/dictionaries'
import type { UserRole } from '../lib/types'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: ApiError | Error | null
  /** True only on the very first load, so refreshes do not blank the screen. */
  initialLoading: boolean
  reload: () => void
  setData: (updater: T | ((current: T | null) => T | null)) => void
}

export interface UseAsyncOptions {
  /** Skip fetching entirely, e.g. while the user is not signed in. */
  enabled?: boolean
  deps?: unknown[]
}

export function useAsync<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  { enabled = true, deps = [] }: UseAsyncOptions = {},
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<Error | null>(null)
  const [attempt, setAttempt] = useState(0)
  // State, not a ref: the flag drives rendering, and a ref flipped in a promise
  // callback would leave the UI showing a spinner that nothing re-renders.
  const [loadedOnce, setLoadedOnce] = useState(false)

  // Callers pass an inline arrow, so the fetcher identity changes every render.
  // Reading it through a ref keeps the effect from re-running, and assigning in
  // an effect rather than during render keeps the render pure. This effect is
  // declared first so the ref is already current when the fetch effect reads it.
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  }, [fetcher])

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let active = true
    // Starting a fetch is synchronising with an external system, which is the
    // case this is here for: the request genuinely begins outside React.
    // oxlint-disable-next-line react/set-state-in-effect
    setLoading(true)
    // oxlint-disable-next-line react/set-state-in-effect
    setError(null)

    void (async () => {
      try {
        const result = await fetcherRef.current(controller.signal)
        if (!active) return
        setData(result)
        setLoadedOnce(true)
      } catch (cause) {
        if (controller.signal.aborted || !active) return
        setError(cause instanceof Error ? cause : new Error(String(cause)))
      } finally {
        if (active) setLoading(false)
      }
    })()

    return () => {
      // Aborting stops a stale request from overwriting newer state when the user
      // clicks through filters faster than the network responds.
      active = false
      controller.abort()
    }
    // `deps` is the caller's own dependency list, spread in on purpose: this hook
    // cannot know what the fetcher closes over, and the alternative is an inline
    // function identity that changes every render and refetches forever.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, attempt, ...deps])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])

  const update = useCallback((updater: T | ((current: T | null) => T | null)) => {
    setData((current) =>
      typeof updater === 'function' ? (updater as (c: T | null) => T | null)(current) : updater,
    )
  }, [])

  return {
    data,
    // `enabled` is applied here rather than by clearing state in the effect, so
    // disabling a fetch cannot leave the caller stuck on a spinner.
    loading: enabled && loading,
    error,
    initialLoading: enabled && loading && !loadedOnce,
    reload,
    setData: update,
  }
}

// --- role-aware navigation -------------------------------------------------

export interface NavItem {
  to: string
  labelKey: TranslationKey
  /**
   * Backend permission the role must hold. These strings come straight from
   * `app/core/rbac.py`, so a role change on the server updates the nav here
   * without touching this file.
   */
  permission?: string
  /**
   * Role restriction for screens where a permission is too broad: a quality
   * inspector can read lots, but has no business browsing the marketplace.
   */
  roles?: UserRole[]
  badge?: number
}

export interface NavGroup {
  headingKey: TranslationKey
  items: NavItem[]
}

/**
 * Groups are ordered by how central they are to each role's job, so the top of
 * the sidebar is the work that matters most for whoever is signed in.
 */
const NAV_GROUPS: NavGroup[] = [
  {
    headingKey: 'nav.dashboard',
    items: [
      { to: '/dashboard', labelKey: 'nav.dashboard', roles: ['FARMER', 'FPO', 'BUYER', 'ADMIN'] },
      { to: '/inspections', labelKey: 'nav.inspections', permission: 'quality:read' },
      { to: '/logistics', labelKey: 'nav.logistics', permission: 'logistics:read' },
      { to: '/admin', labelKey: 'nav.platform', permission: 'admin:dashboard' },
      { to: '/users', labelKey: 'nav.users', permission: 'user:read:all' },
    ],
  },
  {
    headingKey: 'lot.title',
    items: [
      { to: '/lots', labelKey: 'nav.browseLots', permission: 'lot:read', roles: ['BUYER', 'FPO', 'ADMIN'] },
      { to: '/my-lots', labelKey: 'nav.lots', roles: ['FARMER', 'FPO'] },
      { to: '/demands', labelKey: 'nav.browseDemands', permission: 'demand:read', roles: ['FARMER', 'FPO', 'ADMIN'] },
      { to: '/my-demands', labelKey: 'nav.demands', roles: ['BUYER'] },
      { to: '/offers', labelKey: 'nav.offers', permission: 'offer:read' },
      { to: '/orders', labelKey: 'nav.orders', permission: 'order:read' },
    ],
  },
  {
    headingKey: 'market.title',
    items: [
      { to: '/market', labelKey: 'nav.market' },
      // Sellers only: both storage endpoints are scoped to a seller's own or
      // district facilities, so showing this to admin would only produce a 403.
      { to: '/storage', labelKey: 'nav.storage', permission: 'storage:read', roles: ['FARMER', 'FPO'] },
      { to: '/payments', labelKey: 'nav.payments', permission: 'payment:read' },
      {
        to: '/grievances',
        labelKey: 'nav.grievances',
        roles: ['FARMER', 'FPO', 'BUYER', 'LOGISTICS_PARTNER'],
      },
      { to: '/notifications', labelKey: 'nav.notifications' },
      { to: '/profile', labelKey: 'nav.profile' },
    ],
  },
]

interface NavValue {
  groups: NavGroup[]
  canSee: (item: NavItem) => boolean
}

const NavContext = createContext<NavValue | null>(null)

/** Filters `NAV_GROUPS` down to what the signed-in role can actually open. */
export function buildVisibleNav(
  can: (permission: string) => boolean,
  hasRole: (...roles: UserRole[]) => boolean,
): NavGroup[] {
  const visible = (item: NavItem) =>
    (item.permission ? can(item.permission) : true) &&
    (item.roles ? hasRole(...item.roles) : true)
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter(visible),
  })).filter((group) => group.items.length > 0)
}

export function NavProvider({
  can,
  hasRole,
  children,
}: {
  can: (permission: string) => boolean
  hasRole: (...roles: UserRole[]) => boolean
  children: ReactNode
}) {
  const canSee = useCallback(
    (item: NavItem) =>
      (item.permission ? can(item.permission) : true) &&
      (item.roles ? hasRole(...item.roles) : true),
    [can, hasRole],
  )
  const value = useMemo<NavValue>(
    () => ({ groups: buildVisibleNav(can, hasRole), canSee }),
    [can, hasRole, canSee],
  )
  return <NavContext.Provider value={value}>{children}</NavContext.Provider>
}

export function useNav(): NavValue {
  const context = useContext(NavContext)
  if (!context) throw new Error('useNav must be used inside <NavProvider>')
  return context
}

// --- media query -----------------------------------------------------------

/**
 * Subscribes to a media query; used for the mobile sidebar drawer.
 *
 * `useSyncExternalStore` is what this is: `matchMedia` is a browser API outside
 * React, and the value has to be read during render rather than pushed in from
 * an effect, or the first paint after a query change is stale.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    [query],
  )
  const getSnapshot = useCallback(() => window.matchMedia(query).matches, [query])
  // Server snapshot is false, which keeps the markup stable during prerender.
  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}

/** Closes menus and drawers on Escape, which keyboard users expect. */
export function useEscapeKey(active: boolean, onEscape: () => void): void {
  const handler = useRef(onEscape)
  useEffect(() => {
    handler.current = onEscape
  }, [onEscape])
  useEffect(() => {
    if (!active) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') handler.current()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [active])
}
