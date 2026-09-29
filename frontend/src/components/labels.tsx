/**
 * Entity labels: how the UI names backend enum values.
 *
 * The backend sends UPPER_SNAKE constants; showing them raw would read like a
 * database leak. Each constant gets a translated label plus, where the meaning
 * is not obvious, a tone. Unknown values fall through to a prettified version
 * of the constant rather than blank, so a newly added backend status still
 * displays something useful.
 */

import { useI18n } from '../lib/i18n'
import type { TranslationKey } from '../lib/dictionaries'
import type { Tone } from './ui'
import { Badge } from './ui'

/** `PICKUP_SCHEDULED` -> "Pickup scheduled". Covers constants added server-side. */
export function humanise(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .filter(Boolean)
    .map((word, index) => (index === 0 ? word[0].toUpperCase() + word.slice(1) : word))
    .join(' ')
}

export function useStatusLabel() {
  const { t } = useI18n()
  return (value: string | null | undefined): string => {
    if (!value) return '—'
    const key = `status.${value}` as TranslationKey
    const label = t(key)
    // `t` echoes the key back when there is no entry, which is our signal.
    return label === key ? humanise(value) : label
  }
}

/** Order status and lot status share a name; both want distinct labels. */
function orderKey(value: string): TranslationKey | null {
  return value === 'IN_TRANSIT' ? 'status.IN_TRANSIT_ORDER' : (`status.${value}` as TranslationKey)
}

export function StatusBadge({
  value,
  tone = 'neutral',
  domain = 'generic',
}: {
  value: string | null | undefined
  tone?: Tone
  domain?: 'order' | 'lot' | 'offer' | 'demand' | 'payment' | 'generic'
}) {
  const { t } = useI18n()
  if (!value) return null
  const key =
    domain === 'order' ? orderKey(value) : (`status.${value}` as TranslationKey)
  const label = key ? t(key) : value
  return <Badge tone={tone}>{label === key ? humanise(value) : label}</Badge>
}

/**
 * Plain-text role name. `<option>` children must be strings, so screens that
 * put roles in a select use this hook rather than `<RoleLabel />`.
 */
export function useRoleLabel() {
  const { t } = useI18n()
  return (role: string): string => {
    const key = `role.${role}` as TranslationKey
    const label = t(key)
    return label === key ? humanise(role) : label
  }
}

export function RoleLabel({ role }: { role: string }) {
  const label = useRoleLabel()(role)
  return <>{label}</>
}

/** Units are abbreviated in tables but spelled out where space allows. */
/**
 * Plain-text unit name. `<option>` children must be strings, so selects use
 * this hook rather than `<UnitLabel />`.
 */
export function useUnitLabel() {
  const { t } = useI18n()
  return (unit: string | null, long = false): string => {
    if (!unit) return '—'
    const key = `unit.${unit.toLowerCase()}` as TranslationKey
    const label = t(key)
    const known = label !== key
    if (!known) return unit
    return long ? label : known && unit.length > 3 ? unit : label
  }
}

export function UnitLabel({ unit, long = false }: { unit: string | null; long?: boolean }) {
  const label = useUnitLabel()(unit, long)
  return <>{label}</>
}

export function StorageTypeLabel({ type }: { type: string }) {
  const { t } = useI18n()
  const key = `storage.${type}` as TranslationKey
  const label = t(key)
  return <>{label === key ? humanise(type) : label}</>
}

export function GradeBadge({ grade }: { grade: string | null | undefined }) {
  if (!grade) return null
  const tone: Tone = grade === 'A' ? 'success' : grade === 'B' ? 'info' : 'neutral'
  return <Badge tone={tone}>{grade}</Badge>
}
