/**
 * Root error boundary.
 *
 * A render crash inside React unmounts the whole tree, and with no boundary the
 * user gets a blank white page with no way back — the one failure mode with no
 * recovery at all. This catches it, names the error, and offers the two actions
 * that actually help: reload the screen, or clear the session and start again.
 *
 * It is a class component because that is the only way React exposes a catchable
 * render error. It reads the dictionary directly rather than through
 * `useI18n`, because the provider this catches errors from is itself in the tree
 * above and may be the thing that threw.
 */

import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

import { clearTokens } from '../lib/api'
import { dictionaries } from '../lib/dictionaries'
import type { Language, TranslationKey } from '../lib/dictionaries'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
  componentStack: string | null
}

const LANGUAGE_KEY = 'kisansaathi.lang'

/** Best-effort language for the fallback screen; English if we cannot tell. */
function currentLanguage(): Language {
  try {
    return localStorage.getItem(LANGUAGE_KEY) === 'mr' ? 'mr' : 'en'
  } catch {
    return 'en'
  }
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, componentStack: null }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Left in the console rather than swallowed: this is the only trace of a
    // crash the user will not otherwise see.
    console.error('app.crashed', error, info.componentStack)
    this.setState({ componentStack: info.componentStack ?? null })
  }

  /**
   * A full reload, not a state reset. Clearing the boundary state re-renders the
   * same children with the same props, so a crash caused by the state the user
   * just got into throws again immediately and the button appears dead. A reload
   * is the only action that can genuinely recover, and the label promises it.
   */
  private reload = () => window.location.reload()

  private signOut = () => {
    clearTokens()
    window.location.assign('/login')
  }

  render() {
    const { error, componentStack } = this.state
    if (!error) return this.props.children

    const lang = dictionaries[currentLanguage()]
    const t = (key: TranslationKey) => lang[key]

    return (
      <div className="flex min-h-screen items-center justify-center bg-stone-100 p-4">
        <div className="w-full max-w-lg rounded-lg border border-stone-200 bg-white p-5 shadow-sm">
          <h1 className="text-lg font-semibold text-stone-900">{t('app.error')}</h1>
          <p className="mt-2 text-sm text-stone-600">{t('error.boundary.body')}</p>

          <pre className="mt-3 max-h-40 overflow-auto rounded bg-stone-50 p-2 text-xs whitespace-pre-wrap text-stone-700">
            {error.message}
            {componentStack ? `\n${componentStack.trim().split('\n').slice(0, 4).join('\n')}` : ''}
          </pre>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={this.reload}
              className="rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-800"
            >
              {t('error.boundary.retry')}
            </button>
            <button
              type="button"
              onClick={this.signOut}
              className="rounded-md border border-stone-300 px-3 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50"
            >
              {t('error.boundary.signOut')}
            </button>
          </div>
        </div>
      </div>
    )
  }
}
