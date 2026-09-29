/**
 * Notification feed.
 *
 * The feed endpoint is not paginated and returns its own `unread_count`, so this
 * screen does not add a paginator. Marking one read updates the local list and
 * the header badge together, so the count cannot drift from the list.
 */

import { useNavigate } from 'react-router-dom'

import { useAsync } from '../hooks'
import { notifications as notificationsApi } from '../lib/endpoints'
import { useI18n } from '../lib/i18n'
import { Card, EmptyState, ErrorState, Loading, cx } from '../components/ui'
import { Button } from '../components/form'
import type { NotificationList } from '../lib/types'

export function NotificationsPage() {
  const { t, relative } = useI18n()
  const navigate = useNavigate()

  const feed = useAsync<NotificationList>(async () => notificationsApi.list())

  async function markAllRead() {
    await notificationsApi.markAllRead()
    feed.reload()
  }

  async function open(id: string, link: string | null, isRead: boolean) {
    if (!isRead) {
      await notificationsApi.markRead(id)
      feed.reload()
    }
    if (link) navigate(link)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-stone-900">{t('notification.title')}</h1>
        {(feed.data?.unread_count ?? 0) > 0 && (
          <Button variant="secondary" size="sm" onClick={() => void markAllRead()}>
            {t('notification.markAllRead')}
          </Button>
        )}
      </div>

      {(feed.data?.unread_count ?? 0) > 0 && (
        <p className="text-sm text-stone-500">
          {t('notification.unread', { count: feed.data?.unread_count ?? 0 })}
        </p>
      )}

      {feed.initialLoading ? (
        <Loading />
      ) : feed.error ? (
        <ErrorState error={feed.error} onRetry={feed.reload} />
      ) : !feed.data || feed.data.items.length === 0 ? (
        <Card>
          <EmptyState title={t('notification.empty')} hint={t('notification.emptyHint')} />
        </Card>
      ) : (
        <Card padded={false}>
          <ul className="divide-y divide-stone-100">
            {feed.data.items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => void open(item.id, item.link, item.is_read)}
                  className={cx(
                    'flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-stone-50',
                    !item.is_read && 'bg-emerald-50/40',
                  )}
                >
                  <span
                    className={cx(
                      'mt-1.5 size-2 shrink-0 rounded-full',
                      item.is_read ? 'bg-transparent' : 'bg-emerald-600',
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span
                      className={cx(
                        'block text-sm',
                        item.is_read ? 'text-stone-600' : 'font-medium text-stone-900',
                      )}
                    >
                      {item.title}
                    </span>
                    <span className="mt-0.5 block text-sm text-stone-600">{item.body}</span>
                    <span className="mt-1 block text-xs text-stone-400">
                      {relative(item.created_at)}
                    </span>
                  </span>
                  {item.link && (
                    <span className="mt-1 text-xs text-emerald-700">{t('notification.open')}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
