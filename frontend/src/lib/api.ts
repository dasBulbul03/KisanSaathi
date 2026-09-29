/**
 * Typed API client.
 *
 * Three things here are load-bearing and easy to get wrong:
 *
 * 1. **Refresh is single-flight.** A dashboard fires six requests at once; if
 *    the access token has expired they all get 401 at the same moment. Without
 *    a shared in-flight refresh, that means six refresh calls, and the backend
 *    rotates refresh tokens, so the first five would revoke the chain and log
 *    the user out. `refreshInFlight` collapses them into one.
 * 2. **Only one retry.** A failed refresh logs out instead of looping.
 * 3. **Errors carry the code.** The backend returns a stable `code` per failure;
 *    screens branch on that, never on the message text.
 */

const BASE = '/api/v1'
const STORAGE_KEY = 'kisansaathi.auth'

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in?: number
}

export interface ApiErrorBody {
  success: false
  error: {
    code: string
    message: string
    field_errors?: Record<string, string[]>
  }
  request_id: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fieldErrors: Record<string, string[]>
  readonly requestId: string

  constructor(status: number, body: ApiErrorBody | null, fallback: string) {
    super(body?.error?.message || fallback)
    this.name = 'ApiError'
    this.status = status
    this.code = body?.error?.code ?? 'UNKNOWN'
    this.fieldErrors = body?.error?.field_errors ?? {}
    this.requestId = body?.request_id ?? ''
  }

  /** True when the request itself was fine but the caller is not allowed. */
  get isForbidden(): boolean {
    return this.status === 403
  }

  get isNotFound(): boolean {
    return this.status === 404
  }

  /** True when the field errors belong to one named input. */
  errorsFor(field: string): string[] {
    return this.fieldErrors[field] ?? []
  }
}

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
}

let auth: AuthState = loadAuth()
let refreshInFlight: Promise<string | null> | null = null
/** Called when the session cannot be recovered, so the app can react. */
let onSessionLost: (() => void) | null = null

function loadAuth(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { accessToken: null, refreshToken: null }
    const parsed = JSON.parse(raw) as Partial<AuthState>
    return { accessToken: parsed.accessToken ?? null, refreshToken: parsed.refreshToken ?? null }
  } catch {
    // A corrupt entry should log the user out cleanly, not break the app.
    localStorage.removeItem(STORAGE_KEY)
    return { accessToken: null, refreshToken: null }
  }
}

function saveAuth(next: AuthState): void {
  auth = next
  try {
    if (next.accessToken || next.refreshToken) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // Private browsing can refuse storage. The session still works in memory.
  }
}

export function getAccessToken(): string | null {
  return auth.accessToken
}

export function isSignedIn(): boolean {
  return Boolean(auth.accessToken || auth.refreshToken)
}

export function setTokens(tokens: TokenPair): void {
  saveAuth({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token })
}

export function setSessionLostHandler(handler: (() => void) | null): void {
  onSessionLost = handler
}

export function clearTokens(): void {
  saveAuth({ accessToken: null, refreshToken: null })
}

async function readError(response: Response): Promise<ApiErrorBody | null> {
  try {
    return (await response.json()) as ApiErrorBody
  } catch {
    return null
  }
}

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight

  const refreshToken = auth.refreshToken
  if (!refreshToken) return null

  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
      if (!response.ok) {
        clearTokens()
        onSessionLost?.()
        return null
      }
      const tokens = (await response.json()) as TokenPair
      setTokens(tokens)
      return tokens.access_token
    } catch {
      // Network failure is not a revoked session; keep the tokens and let the
      // original error surface rather than throwing the user out.
      return null
    } finally {
      refreshInFlight = null
    }
  })()

  return refreshInFlight
}

/** Query values are flattened to primitives; nested objects are not a thing here. */
export type QueryParams = Record<string, unknown>

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  query?: QueryParams
  /** Internal: prevents an infinite refresh loop. */
  retried?: boolean
  /** Set for login/register so a 401 is not treated as an expired session. */
  skipAuth?: boolean
  signal?: AbortSignal
}

function buildUrl(path: string, query?: QueryParams): string {
  const url = `${BASE}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, raw] of Object.entries(query)) {
    // Dropping empty values keeps the URL clean and matches the backend's
    // optional-parameter handling.
    if (raw === null || raw === undefined || raw === '') continue
    params.append(key, String(raw))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, retried = false, skipAuth = false, signal } = options
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (!skipAuth && auth.accessToken) {
    headers.Authorization = `Bearer ${auth.accessToken}`
  }

  const response = await fetch(buildUrl(path, query), {
    method,
    headers,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...(signal ? { signal } : {}),
  })

  if (response.status === 401 && !skipAuth && !retried) {
    const renewed = await refreshAccessToken()
    if (renewed) {
      return request<T>(path, { ...options, retried: true })
    }
  }

  if (!response.ok) {
    const errorBody = await readError(response)
    if (response.status === 401 && !skipAuth) {
      clearTokens()
      onSessionLost?.()
    }
    throw new ApiError(
      response.status,
      errorBody,
      `Request failed with status ${response.status}`,
    )
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, query?: RequestOptions['query'], signal?: AbortSignal) =>
    request<T>(path, { method: 'GET', query, ...(signal ? { signal } : {}) }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
