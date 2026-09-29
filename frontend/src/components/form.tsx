/**
 * Form primitives.
 *
 * Two decisions worth knowing:
 *
 * - Labels are always visible, never placeholder-only. Farmers work in bright
 *   fields with sunlight on the screen, and a label that disappears on focus is
 *   unreadable there.
 * - `required` marks the label visually and sets the native attribute, but
 *   client-side validation is left to the browser. Anything stricter belongs on
 *   the server, which owns the rules.
 */

import { useId } from 'react'
import type { ChangeEvent, ReactNode } from 'react'

import { useI18n } from '../lib/i18n'
import { cx } from './ui'

const CONTROL =
  'w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 shadow-xs outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 disabled:bg-stone-100 disabled:text-stone-500'

const LABEL = 'block text-sm font-medium text-stone-700'

export function Field({
  label,
  hint,
  error,
  required,
  children,
  htmlFor,
}: {
  label: string
  hint?: string
  error?: string
  required?: boolean
  children: ReactNode
  htmlFor: string
}) {
  return (
    <div className="space-y-1">
      <label className={LABEL} htmlFor={htmlFor}>
        {label}
        {required && <span className="ml-0.5 text-red-600">*</span>}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-red-600">{error}</p>
      ) : hint ? (
        <p className="text-xs text-stone-500">{hint}</p>
      ) : null}
    </div>
  )
}

export function TextInput({
  id,
  label,
  value,
  onChange,
  hint,
  error,
  required,
  type = 'text',
  autoComplete,
  inputMode,
  maxLength,
  min,
  max,
  step,
  placeholder,
  disabled,
}: {
  id?: string
  label: string
  value: string
  onChange: (value: string) => void
  hint?: string
  error?: string
  required?: boolean
  type?: 'text' | 'tel' | 'email' | 'password' | 'number' | 'date'
  autoComplete?: string
  inputMode?: 'numeric' | 'decimal' | 'tel' | 'text' | 'email'
  maxLength?: number
  min?: number | string
  max?: number | string
  step?: number | string
  placeholder?: string
  disabled?: boolean
}) {
  const generated = useId()
  const fieldId = id ?? generated
  return (
    <Field label={label} hint={hint} error={error} required={required} htmlFor={fieldId}>
      <input
        id={fieldId}
        type={type}
        value={value}
        required={required}
        disabled={disabled}
        autoComplete={autoComplete}
        inputMode={inputMode}
        maxLength={maxLength}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
        className={cx(CONTROL, error && 'border-red-400 focus:border-red-600 focus:ring-red-600/20')}
      />
    </Field>
  )
}

export function TextArea({
  id,
  label,
  value,
  onChange,
  hint,
  error,
  required,
  rows = 3,
  maxLength,
  placeholder,
}: {
  id?: string
  label: string
  value: string
  onChange: (value: string) => void
  hint?: string
  error?: string
  required?: boolean
  rows?: number
  maxLength?: number
  placeholder?: string
}) {
  const generated = useId()
  const fieldId = id ?? generated
  return (
    <Field label={label} hint={hint} error={error} required={required} htmlFor={fieldId}>
      <textarea
        id={fieldId}
        rows={rows}
        value={value}
        required={required}
        maxLength={maxLength}
        placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)}
        className={cx(CONTROL, 'resize-y', error && 'border-red-400')}
      />
    </Field>
  )
}

export interface SelectOption {
  value: string
  label: string
}

/**
 * A native `<select>` rather than a custom listbox: it gets the phone's own
 * picker, which is far easier to use than a styled div in a village with patchy
 * network. Its first option can be a disabled placeholder.
 */
export function Select({
  id,
  label,
  value,
  onChange,
  options,
  hint,
  error,
  required,
  placeholder,
  disabled,
}: {
  id?: string
  label: string
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  hint?: string
  error?: string
  required?: boolean
  placeholder?: string
  disabled?: boolean
}) {
  const generated = useId()
  const fieldId = id ?? generated
  return (
    <Field label={label} hint={hint} error={error} required={required} htmlFor={fieldId}>
      <select
        id={fieldId}
        value={value}
        required={required}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        onChange={(event) => onChange(event.target.value)}
        className={cx(CONTROL, !value && 'text-stone-500', error && 'border-red-400')}
      >
        {placeholder !== undefined && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  )
}

export function Checkbox({
  id,
  label,
  checked,
  onChange,
  hint,
}: {
  id?: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  hint?: string
}) {
  const generated = useId()
  const fieldId = id ?? generated
  return (
    <div className="flex items-start gap-2">
      <input
        id={fieldId}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 size-4 rounded border-stone-300 text-emerald-600 focus:ring-emerald-600"
      />
      <div>
        <label htmlFor={fieldId} className="text-sm text-stone-800">
          {label}
        </label>
        {hint && <p className="text-xs text-stone-500">{hint}</p>}
      </div>
    </div>
  )
}

export function Button({
  children,
  onClick,
  type = 'button',
  variant = 'primary',
  size = 'md',
  disabled,
  busy,
  className,
}: {
  children: ReactNode
  onClick?: () => void
  type?: 'button' | 'submit'
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  disabled?: boolean
  busy?: boolean
  className?: string
}) {
  const { t } = useI18n()
  const variants = {
    primary: 'bg-emerald-700 text-white hover:bg-emerald-800 disabled:bg-emerald-700/50',
    secondary: 'border border-stone-300 bg-white text-stone-800 hover:bg-stone-50',
    ghost: 'text-stone-700 hover:bg-stone-100',
    danger: 'bg-red-600 text-white hover:bg-red-700',
  }
  const sizes = { sm: 'px-2.5 py-1.5 text-xs', md: 'px-4 py-2 text-sm' }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || busy}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60',
        variants[variant],
        sizes[size],
        className,
      )}
    >
      {busy && (
        <span
          className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
          aria-hidden
        />
      )}
      {busy ? t('app.saving') : children}
    </button>
  )
}
