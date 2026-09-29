/**
 * Quality inspections.
 *
 * The grade-suggestion panel is advisory. It runs the same threshold logic the
 * backend uses, so a seller can check where their produce would land before
 * booking an inspector, but the copy says plainly that only an inspector's
 * sign-off is a real grade. Overstating that would let a Grade B lot be priced
 * as Grade A.
 */

import { useState } from 'react'

import { useAuth } from '../auth/AuthContext'
import { useAsync } from '../hooks'
import { markets, quality as qualityApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Badge, Card, EmptyState, ErrorState, Loading, Paginator, Table, cx } from '../components/ui'
import { Button, Select, TextInput } from '../components/form'
import { GradeBadge, StatusBadge } from '../components/labels'
import type { Commodity, GradeSuggestion, Page, QualityAttribute, QualityInspection } from '../lib/types'

export function InspectionsPage() {
  const { t, number, dateTime } = useI18n()
  const { can } = useAuth()
  const [page, setPage] = useState(1)
  const [tab, setTab] = useState<'pending' | 'all'>('pending')

  const pending = useAsync<Page<QualityInspection>>(
    async () => qualityApi.pending({ page }),
    { enabled: tab === 'pending', deps: [page] },
  )
  const all = useAsync<Page<QualityInspection>>(
    async () => qualityApi.inspections({ page }),
    { enabled: tab === 'all', deps: [page] },
  )

  const source = tab === 'pending' ? pending : all
  const items = source.data?.items ?? []

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-stone-900">{t('quality.title')}</h1>

      <Card>
        <div className="flex gap-2">
          {(['pending', 'all'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setTab(value)
                setPage(1)
              }}
              className={cx(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                tab === value
                  ? 'bg-emerald-700 text-white'
                  : 'bg-white text-stone-700 ring-1 ring-stone-300 ring-inset hover:bg-stone-50',
              )}
            >
              {value === 'pending' ? t('quality.pending') : t('quality.inspections')}
            </button>
          ))}
        </div>
      </Card>

      {source.initialLoading ? (
        <Loading />
      ) : source.error ? (
        <ErrorState error={source.error} onRetry={source.reload} />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            title={tab === 'pending' ? t('quality.noPending') : t('quality.noInspections')}
          />
        </Card>
      ) : (
        <Card padded={false}>
          <Table
            caption={t('quality.inspections')}
            columns={[
              t('order.number'),
              t('quality.grade'),
              t('quality.moisture'),
              t('quality.damage'),
              t('quality.inspector'),
              t('quality.inspectedAt'),
              t('status.label'),
            ]}
          >
            {items.map((inspection) => (
              <tr key={inspection.id}>
                <td className="px-3 py-2 text-xs text-stone-700">{inspection.lot_id.slice(0, 8)}</td>
                <td className="px-3 py-2">
                  <GradeBadge grade={inspection.grade} />
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  {inspection.moisture_percent !== null
                    ? `${number(inspection.moisture_percent)}%`
                    : '—'}
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  {inspection.damage_percent !== null ? `${number(inspection.damage_percent)}%` : '—'}
                </td>
                <td className="px-3 py-2 text-xs text-stone-700">
                  {inspection.inspector_name ?? '—'}
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-stone-500">
                  {dateTime(inspection.inspected_at)}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge value={inspection.status} />
                  {inspection.is_demo && <Badge tone="warning">demo</Badge>}
                </td>
              </tr>
            ))}
          </Table>
          <div className="px-4">
            <Paginator meta={source.data?.meta ?? null} onPage={setPage} />
          </div>
        </Card>
      )}

      {can('quality:submit') && <GradeChecker />}
    </div>
  )
}

/** Advisory grade check driven by the commodity's quality attributes. */
function GradeChecker() {
  const { t, number } = useI18n()
  const commodities = useAsync<Commodity[]>(async () => markets.commodities())
  const [commodityId, setCommodityId] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [result, setResult] = useState<GradeSuggestion | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const attributes = useAsync<QualityAttribute[]>(
    async () => qualityApi.attributes(commodityId),
    { enabled: Boolean(commodityId), deps: [commodityId] },
  )

  async function check(event: React.FormEvent) {
    event.preventDefault()
    const measurements = Object.entries(values)
      .filter(([, value]) => value !== '')
      .map(([attribute_code, value]) => ({ attribute_code, value: Number(value) }))
    if (measurements.length === 0) {
      setResult(null)
      return
    }
    setBusy(true)
    setError(null)
    try {
      setResult(await qualityApi.suggestGrade({ commodity_id: commodityId, measurements }))
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title={t('quality.gradeCheck')} subtitle={t('quality.gradeCheckHint')}>
      <form onSubmit={check} className="space-y-3">
        <Select
          label={t('lot.commodity')}
          value={commodityId}
          onChange={(value) => {
            setCommodityId(value)
            setValues({})
            setResult(null)
          }}
          required
          placeholder={t('form.selectCommodity')}
          options={(commodities.data ?? []).map((commodity) => ({
            value: commodity.id,
            label: commodity.name,
          }))}
        />

        {attributes.data && attributes.data.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {attributes.data.map((attribute) => (
              <TextInput
                key={attribute.id}
                label={`${attribute.label}${attribute.unit ? ` (${attribute.unit})` : ''}`}
                value={values[attribute.code] ?? ''}
                onChange={(value) =>
                  setValues((current) => ({ ...current, [attribute.code]: value }))
                }
                type="number"
                inputMode="decimal"
                step="any"
                hint={t('quality.ideal')}
              />
            ))}
          </div>
        )}

        {attributes.initialLoading && <Loading label={t('app.loading')} />}

        {error ? <ErrorState error={error} /> : null}

        <Button type="submit" busy={busy}>
          {t('quality.gradeCheck')}
        </Button>
      </form>

      {result && (
        <div className="mt-4 rounded-lg border border-stone-200 bg-stone-50 p-3">
          {result.suggested_grade ? (
            <p className="flex items-center gap-2 text-sm">
              <span className="text-stone-600">{t('quality.gradeCheck')}:</span>
              <GradeBadge grade={result.suggested_grade} />
            </p>
          ) : (
            <p className="text-sm text-stone-600">{t('quality.noSuggestion')}</p>
          )}
          <p className="mt-1 text-xs text-stone-500">{result.reason}</p>
          <ul className="mt-2 space-y-1">
            {result.checks.map((check) => (
              <li key={check.code} className="flex items-center justify-between text-xs">
                <span className="text-stone-600">{check.label}</span>
                <span
                  className={cx(
                    'font-medium',
                    check.satisfied ? 'text-emerald-700' : 'text-amber-700',
                  )}
                >
                  {number(check.value)} {check.unit}
                  {check.ideal_min !== null || check.ideal_max !== null ? (
                    <span className="ml-1 font-normal text-stone-500">
                      ({check.ideal_min ?? '—'}–{check.ideal_max ?? '—'})
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-stone-500">{t('quality.instruction')}</p>
        </div>
      )}
    </Card>
  )
}
