/**
 * Dependency-free Chrome DevTools Protocol client.
 *
 * Enough to load the app in headless Chrome, sign in, and report what actually
 * rendered: console errors, uncaught exceptions, and the visible text. Written
 * with Node's built-in WebSocket so there is nothing to install.
 *
 * Usage: node scripts/browser_check.mjs [baseUrl] [phone] [password]
 */
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const PHONE = process.argv[3] ?? '9000000002'
const PASSWORD = process.argv[4] ?? 'Demo@1234'
const CHROME =
  process.env.CHROME_PATH ??
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const PORT = 9333

const profile = mkdtempSync(join(tmpdir(), 'ks-chrome-'))
const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--window-size=1280,900',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function endpoint() {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      if (res.ok) return (await res.json()).webSocketDebuggerUrl
    } catch {
      /* not up yet */
    }
    await sleep(250)
  }
  throw new Error('Chrome did not expose a debugging endpoint')
}

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

  close() {
    this.#ws.close()
  }
}

const problems = []
const notes = []

try {
  const browser = await Cdp.connect(await endpoint())
  const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank' })
  const { sessionId } = await browser.send('Target.attachToTarget', {
    targetId,
    flatten: true,
  })
  const call = (method, params) => browser.send(method, params, sessionId)

  browser.on('Runtime.consoleAPICalled', (p) => {
    if (p.type === 'error' || p.type === 'warning') {
      problems.push(`console.${p.type}: ${p.args.map((a) => a.value ?? a.description).join(' ')}`)
    }
  })
  browser.on('Runtime.exceptionThrown', (p) => {
    const d = p.exceptionDetails
    problems.push(`exception: ${d.exception?.description ?? d.text}`)
  })
  browser.on('Log.entryAdded', (p) => {
    if (p.entry.level === 'error') problems.push(`log: ${p.entry.text} ${p.entry.url ?? ''}`)
  })

  await call('Runtime.enable')
  await call('Log.enable')
  await call('Page.enable')
  await call('Page.navigate', { url: `${BASE}/login` })
  await sleep(2500)

  const read = async () => {
    const { result } = await call('Runtime.evaluate', {
      expression: `(() => {
        const root = document.getElementById('root');
        return JSON.stringify({
          url: location.pathname,
          title: document.title,
          nodes: root ? root.childElementCount : -1,
          text: (root?.innerText ?? '').replace(/\\s+/g, ' ').trim().slice(0, 400),
          html: (root?.innerHTML ?? '').length,
          // The nav is role-filtered in the client, so what it lists is the only
          // way to see from a browser whether a buyer is being shown transport or
          // quality links that the API would answer with 403.
          nav: [...document.querySelectorAll('nav a')]
            .map((a) => a.getAttribute('href'))
            .filter(Boolean),
        });
      })()`,
      returnByValue: true,
    })
    return JSON.parse(result.value)
  }

  const loginPage = await read()
  notes.push(`login page: ${loginPage.nodes} root nodes, ${loginPage.html} bytes, "${loginPage.text.slice(0, 80)}"`)

  // Sign in through the app's own API layer, exactly as the form would.
  const { result: auth } = await call('Runtime.evaluate', {
    expression: `(async () => {
      const body = { identifier: ${JSON.stringify(PHONE)}, password: ${JSON.stringify(PASSWORD)} };
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) return JSON.stringify({ error: res.status });
      const tokens = await res.json();
      const me = await fetch('/api/v1/auth/me', {
        headers: { Authorization: 'Bearer ' + tokens.access_token },
      });
      const profile = await me.json();
      localStorage.setItem('kisansaathi.auth', JSON.stringify({
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
      }));
      return JSON.stringify({ role: profile.user.role });
    })()`,
    awaitPromise: true,
    returnByValue: true,
  })
  if (auth.value.includes('error')) throw new Error(`login failed: ${auth.value}`)

  await call('Page.navigate', { url: `${BASE}/` })
  await sleep(3000)
  const home = await read()
  notes.push(`after login: ${home.url} -> ${home.nodes} root nodes, ${home.html} bytes`)
  notes.push(`visible text: "${home.text.slice(0, 200)}"`)
  notes.push(`nav links: ${home.nav.join(' ') || '(none)'}`)

  if (home.nodes === 0 || home.html < 200) problems.push('blank page: #root has no content')

  await call('Page.captureScreenshot', {}).then(async ({ data }) => {
    const { writeFileSync } = await import('node:fs')
    writeFileSync('/tmp/ks-after-login.png', Buffer.from(data, 'base64'))
  })

  browser.close()
} catch (error) {
  problems.push(`harness: ${error.message}`)
} finally {
  chrome.kill()
  // Chrome writes to its profile as it exits, so give it a moment before the
  // cleanup rather than racing it and failing the whole run.
  await sleep(500)
  try {
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
  } catch {
    /* a leftover temp profile is not worth failing over */
  }
}

console.log(notes.join('\n'))
if (problems.length) {
  console.log('\nPROBLEMS:')
  for (const p of problems) console.log(' - ' + p)
  process.exit(1)
}
console.log('\nno console errors, no exceptions, page has content')
