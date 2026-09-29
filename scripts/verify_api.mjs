#!/usr/bin/env node
/**
 * Frontend/backend contract check.
 *
 * The frontend's API layer is hand-written against the backend's OpenAPI schema,
 * and hand-written contracts drift. This script signs in as every demo role and
 * calls every endpoint a screen actually uses, so a renamed field or a route
 * that moved shows up here instead of as a blank page in a browser.
 *
 * Usage (backend and `npm run dev` must both be running):
 *   node scripts/verify_api.mjs
 *   BASE_URL=http://localhost:5173/api/v1 node scripts/verify_api.mjs
 *
 * Exits non-zero when any call a screen depends on fails.
 */

const BASE = process.env.BASE_URL ?? 'http://localhost:5173/api/v1'
const PASSWORD = 'Demo@1234'

/**
 * The storage options endpoint is deliberately seller-only, so these two 403s
 * are the contract working, not a fault. Anything else non-2xx is a failure.
 */
const EXPECTED_DENIALS = new Set(['BUYER /storage/options', 'ADMIN /storage/options'])

const ACCOUNTS = [
  { label: 'FARMER', phone: '9000000002' },
  { label: 'FARMER2', phone: '9000000003' },
  { label: 'FPO', phone: '9000000004' },
  { label: 'BUYER', phone: '9000000005' },
  { label: 'BUYER2', phone: '9000000006' },
  { label: 'INSPECTOR', phone: '9000000007' },
  { label: 'LOGISTICS', phone: '9000000008' },
  { label: 'ADMIN', phone: '9000000001' },
]

/**
 * Endpoints that answer with a bare array. Everything else in this list is a
 * JSON object, usually `{items, meta}`. Pinning the container matters: a route
 * that changes from a list to an envelope (or the reverse) renders as an empty
 * screen in the client with no error anywhere.
 */
const BARE_ARRAY_PATHS = [
  /\/orders\/pipeline$/,
  /\/payments\/due-soon$/,
  /\/storage\/options$/,
  /\/quality\/inspections\/pending$/,
  /\/lots\/[^/]+\/matches$/,
  /\/offers\/lot\/[^/]+$/,
]

function expectContainer(path, data, label) {
  if (data === null) {
    record(`${label} ${path} shape`, 500, 'no JSON body')
    return
  }
  const shouldBeArray = BARE_ARRAY_PATHS.some((pattern) => pattern.test(path))
  if (shouldBeArray && !Array.isArray(data)) {
    record(`${label} ${path} shape`, 500, `expected an array, got ${typeof data}`)
  }
  if (!shouldBeArray && Array.isArray(data)) {
    record(`${label} ${path} shape`, 500, 'expected an object, got an array')
  }
}

/** Endpoints each role's screens load on open. */
const PATHS_BY_ROLE = {
  COMMON: ['/auth/me', '/notifications', '/notifications/unread-count', '/orders/pipeline'],
  FARMER: [
    '/dashboards/farmer',
    '/lots/mine',
    '/lots/stats',
    '/offers',
    '/orders',
    '/payments/summary',
    '/payments/due-soon',
    '/storage/mine',
    '/logistics',
  ],
  FPO: ['/dashboards/farmer', '/lots/mine', '/offers', '/orders', '/storage/mine'],
  BUYER: ['/dashboards/buyer', '/lots', '/demands/mine', '/offers', '/orders'],
  INSPECTOR: ['/quality/inspections', '/quality/inspections/pending'],
  LOGISTICS: ['/logistics', '/orders'],
  ADMIN: [
    '/dashboards/admin',
    '/admin/users',
    '/admin/users/counts',
    '/payments/summary/platform',
    '/lots',
    '/demands',
  ],
  MARKET: ['/markets/commodities'],
}

const results = []

async function call(path, { method = 'GET', token, body } = {}) {
  const response = await fetch(BASE + path, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  let data = null
  try {
    data = await response.json()
  } catch {
    // A non-JSON body is itself a finding; leave `data` null.
  }
  return { status: response.status, data }
}

function record(label, status, note = '') {
  results.push({ label, status, note })
}

async function login(phone) {
  const { status, data } = await call('/auth/login', {
    method: 'POST',
    body: { identifier: phone, password: PASSWORD },
  })
  if (status !== 200) throw new Error(`login failed for ${phone}: ${status} ${JSON.stringify(data)}`)
  return data.access_token
}

for (const { label, phone } of ACCOUNTS) {
  let token
  try {
    token = await login(phone)
  } catch (error) {
    record(label, 0, String(error.message))
    continue
  }
  record(`${label} login`, 200)

  const paths = [...PATHS_BY_ROLE.COMMON]
  if (label.startsWith('FARMER') || label === 'FPO') paths.push(...PATHS_BY_ROLE.FARMER)
  if (label.startsWith('BUYER')) paths.push(...PATHS_BY_ROLE.BUYER)
  if (label === 'ADMIN') paths.push(...PATHS_BY_ROLE.ADMIN)
  if (label === 'INSPECTOR') paths.push(...PATHS_BY_ROLE.INSPECTOR)
  if (label === 'LOGISTICS') paths.push(...PATHS_BY_ROLE.LOGISTICS)
  // Storage options are seller-only. The two branches are mutually exclusive:
  // a seller must be able to read them, and the other two roles must be refused.
  if (label.startsWith('FARMER') || label === 'FPO') paths.push('/storage/options')
  if (label === 'BUYER' || label === 'ADMIN') paths.push('/storage/options')

  for (const path of paths) {
    const { status, data } = await call(path, { token })
    record(`${label} ${path}`, status, data?.error?.code ?? '')
    if (status < 400) expectContainer(path, data, label)
  }
}

// The market screens need a commodity before anything else resolves.
const commodities = (await call('/markets/commodities')).data ?? []
if (!commodities.length) {
  record('commodities', 500, 'no commodities seeded')
} else {
  const id = commodities[0].id
  for (const path of [
    `/markets/price-snapshot?commodity_id=${id}`,
    `/markets/prices/trend?commodity_id=${id}&days=30`,
    `/markets/prices/comparison?commodity_id=${id}`,
  ]) {
    const { status, data } = await call(path)
    record(`MARKET ${path.split('?')[0]}`, status, data?.error?.code ?? '')
    if (status < 400) expectContainer(path, data, 'MARKET')
  }
}

// Lot and demand detail pages, reached by clicking a row.
const buyerToken = await login('9000000005')
const farmerToken = await login('9000000002')
const { data: lots } = await call('/lots?page=1&page_size=1', { token: buyerToken })
const lotId = lots?.items?.[0]?.id
if (!lotId) {
  record('lot detail', 500, 'no published lot to open')
} else {
  for (const path of [`/lots/${lotId}`, `/lots/${lotId}/matches`, `/offers/lot/${lotId}`]) {
    const { status, data } = await call(path, { token: buyerToken })
    record(`BUYER ${path.split('/').slice(2).join('/')}`, status, data?.error?.code ?? '')
    if (status < 400) expectContainer(path, data, 'BUYER')
  }
}

const { data: myLots } = await call('/lots/mine', { token: farmerToken })
const myLotId = myLots?.items?.[0]?.id
if (myLotId) {
  // A match list must be an array; it once came back as an object and the page
  // silently rendered nothing.
  const { status, data } = await call(`/lots/${myLotId}/matches`, { token: farmerToken })
  record(`FARMER /lots/{id}/matches`, status, data?.error?.code ?? '')
  if (!Array.isArray(data)) record('FARMER matches is an array', 500, typeof data)
}

const { data: demands } = await call('/demands?page=1&page_size=1', { token: farmerToken })
const demandId = demands?.items?.[0]?.id
if (demandId) {
  const { status } = await call(`/demands/${demandId}`, { token: farmerToken })
  record('FARMER /demands/{id}', status)
}

// Every notification link has to be a route the client can actually open.
const { data: feed } = await call('/notifications', { token: farmerToken })
for (const item of feed?.items ?? []) {
  if (item.link && !item.link.startsWith('/')) {
    record(`notification link ${item.notification_type}`, 500, item.link)
  }
}

const failures = results.filter((r) => {
  if (r.status < 400) return false
  return !EXPECTED_DENIALS.has(r.label)
})
const denials = results.filter((r) => r.status >= 400 && EXPECTED_DENIALS.has(r.label))

console.log(`\n${results.length} checks, ${failures.length} failed, ${denials.length} expected denials`)
if (failures.length) {
  for (const r of failures) console.log(`  FAIL ${r.label} -> ${r.status} ${r.note}`)
}
for (const r of denials) console.log(`  ok   ${r.label} -> ${r.status} (role boundary)`)
process.exit(failures.length ? 1 : 0)
