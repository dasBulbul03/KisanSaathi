/**
 * Sweep every demo account across every route the app serves, in headless
 * Chrome, and report any route that renders empty or throws.
 *
 * A white screen is a crash with no error boundary, and a crash only shows up
 * when the component actually runs. Signing in and clicking through all eight
 * accounts is the only way to find them without a browser to look at.
 *
 * Usage: node scripts/browser_sweep.mjs [baseUrl]
 */
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const PASSWORD = 'Demo@1234'
const CHROME =
  process.env.CHROME_PATH ??
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const PORT = 9334

const ACCOUNTS = [
  { label: 'ADMIN', phone: '9000000001', landing: '/dashboard' },
  { label: 'FARMER', phone: '9000000002', landing: '/dashboard' },
  { label: 'FARMER2', phone: '9000000003', landing: '/dashboard' },
  { label: 'FPO', phone: '9000000004', landing: '/dashboard' },
  { label: 'BUYER', phone: '9000000005', landing: '/dashboard' },
  { label: 'BUYER2', phone: '9000000006', landing: '/dashboard' },
  { label: 'INSPECTOR', phone: '9000000007', landing: '/inspections' },
  { label: 'LOGISTICS', phone: '9000000008', landing: '/logistics' },
]

const ROUTES = [
  '/dashboard',
  '/my-lots',
  '/my-lots/new',
  '/demands',
  '/my-demands',
  '/my-demands/new',
  '/offers',
  '/orders',
  '/market',
  '/storage',
  '/payments',
  '/logistics',
  '/inspections',
  '/grievances',
  '/notifications',
  '/profile',
  '/admin/users',
]

const profile = mkdtempSync(join(tmpdir(), 'ks-sweep-'))
const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

class Cdp {
  #ws
  #id = 0
  #pending = new Map()
  #handlers = new Map()

  static async connect(url) {
    const cdp = new Cdp()
    cdp.#ws = new WebSocket(url)
    await new Promise((resolve, reject) => {
      cdp.#ws.addEventListener('open', resolve, { once: true })
      cdp.#ws.addEventListener('error', reject, { once: true })
    })
    cdp.#ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data)
      if (msg.id && cdp.#pending.has(msg.id)) {
        const { resolve, reject } = cdp.#pending.get(msg.id)
        cdp.#pending.delete(msg.id)
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result)
      } else if (msg.method) {
        for (const fn of cdp.#handlers.get(msg.method) ?? []) fn(msg.params)
      }
    })
    return cdp
  }

  on(method, fn) {
    if (!this.#handlers.has(method)) this.#handlers.set(method, [])
    this.#handlers.get(method).push(fn)
  }

  send(method, params = {}, sessionId) {
    const id = ++this.#id
    return new Promise((resolve, reject) => {
      this.#pending.set(id, { resolve, reject })
      this.#ws.send(JSON.stringify({ id, method, params, sessionId }))
    })
  }
}

let current = 'startup'
const problems = []
/** Console noise recorded during the current route, reported with it. */
let routeConsole = []

try {
  let url
  for (let i = 0; i < 60 && !url; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      if (res.ok) url = (await res.json()).webSocketDebuggerUrl
    } catch {
      /* not up yet */
    }
    if (!url) await sleep(250)
  }
  const browser = await Cdp.connect(url)
  const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank' })
  const { sessionId } = await browser.send('Target.attachToTarget', { targetId, flatten: true })
  const call = (method, params) => browser.send(method, params, sessionId)

  browser.on('Runtime.consoleAPICalled', (p) => {
    if (p.type === 'error' || p.type === 'warning') {
      const text = p.args.map((a) => a.value ?? a.description).join(' ').replace(/\s+/g, ' ')
      routeConsole.push(`console.${p.type}: ${text.slice(0, 200)}`)
    }
  })
  browser.on('Runtime.exceptionThrown', (p) => {
    const d = p.exceptionDetails
    routeConsole.push(`exception: ${(d.exception?.description ?? d.text).split('\n')[0]}`)
  })

  await call('Runtime.enable')
  await call('Page.enable')
  await call('Page.navigate', { url: `${BASE}/login` })
  await sleep(2000)

  const evaluate = async (expression) => {
    const { result, exceptionDetails } = await call('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    })
    if (exceptionDetails) throw new Error(exceptionDetails.text + ' ' + (exceptionDetails.exception?.description ?? ''))
    return result.value
  }

  for (const account of ACCOUNTS) {
    const login = await evaluate(`(async () => {
      localStorage.clear();
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: ${JSON.stringify(account.phone)}, password: ${JSON.stringify(PASSWORD)} }),
      });
      if (!res.ok) return 'HTTP ' + res.status;
      const tokens = await res.json();
      localStorage.setItem('kisansaathi.auth', JSON.stringify({
        accessToken: tokens.access_token, refreshToken: tokens.refresh_token,
      }));
      return 'ok';
    })()`)
    if (login !== 'ok') {
      problems.push(`${account.label} could not log in: ${login}`)
      continue
    }

    for (const route of ROUTES) {
      current = `${account.label} ${route}`
      // A role without permission lands on its own dashboard; that is a redirect
      // working, not a fault, so only a genuinely empty or broken render counts.
      routeConsole = []
      await call('Page.navigate', { url: BASE + route })
      await sleep(900)
      const state = await evaluate(`(() => {
        const root = document.getElementById('root');
        return JSON.stringify({
          at: location.pathname,
          bytes: (root?.innerHTML ?? '').length,
          text: (root?.innerText ?? '').replace(/\\s+/g, ' ').trim().slice(0, 90),
        });
      })()`)
      const { at, bytes, text } = JSON.parse(state)
      const redirected = at !== route
      // Rendering without throwing is not enough: "undefined" or "NaN" on
      // screen is a broken screen that no status code reveals.
      const broken = ['undefined', 'NaN', '[object Object]'].filter((needle) =>
        text.includes(needle),
      )
      if (bytes < 200) {
        problems.push(`${account.label} ${route} -> ${at}: EMPTY (${bytes} bytes) ${text}`)
      } else if (broken.length) {
        problems.push(`${account.label} ${route}: shows ${broken.join(', ')} — "${text}"`)
      } else if (routeConsole.length) {
        problems.push(`${account.label} ${route}: ${routeConsole.join(' | ')}`)
      } else {
        console.log(`  ok ${account.label.padEnd(9)} ${route.padEnd(16)} ${redirected ? '-> ' + at + ' ' : ''}${bytes} bytes`)
      }
    }
  }
  browser.send('Target.closeTarget', { targetId }).catch(() => {})
} catch (error) {
  problems.push(`harness: ${error.message}`)
} finally {
  chrome.kill()
  await sleep(500)
  try {
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
  } catch {
    /* leftover temp profile is not worth failing over */
  }
}

if (problems.length) {
  console.log('\nPROBLEMS:')
  for (const p of problems) console.log(' - ' + p)
  process.exit(1)
}
console.log('\nall routes rendered for all accounts')
