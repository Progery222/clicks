import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError, type Dashboard, type LinkRow } from '../api'
import { Avatar, Modal } from '../components'

function splitAccounts(display: string | null | undefined): string[] {
  return String(display || '')
    .split(/\n+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function AccountCell({
  display,
  platformIconUrl,
  platformLabel,
  expanded,
  onToggle,
}: {
  display: string
  platformIconUrl?: string | null
  platformLabel?: string
  expanded: boolean
  onToggle: () => void
}) {
  const accounts = splitAccounts(display)
  if (!accounts.length) return <span className="muted">—</span>
  const rest = accounts.length - 1
  const visible = expanded || rest <= 0 ? accounts : [accounts[0]]
  return (
    <span className="row" style={{ gap: '0.45rem', alignItems: 'flex-start' }}>
      <Avatar url={platformIconUrl} name={platformLabel || accounts[0]} />
      <span style={{ whiteSpace: 'pre-line' }}>
        {visible.join('\n')}
        {rest > 0 ? (
          <>
            {' '}
            <button
              type="button"
              className="btn btn-ghost"
              style={{ padding: '0 0.25rem', minHeight: 0, fontWeight: 600 }}
              onClick={(e) => {
                e.stopPropagation()
                onToggle()
              }}
              aria-expanded={expanded}
              title={expanded ? 'Свернуть' : `Показать ещё ${rest}`}
            >
              {expanded ? 'свернуть' : `+${rest}`}
            </button>
          </>
        ) : null}
      </span>
    </span>
  )
}

export function LinksPage() {
  const [sp, setSp] = useSearchParams()
  const nav = useNavigate()
  const platform = sp.get('platform') || 'all'
  const account = sp.get('account') || ''
  const destination = sp.get('destination') || 'all'
  const preset = sp.get('preset') || 'all'
  const sort = sp.get('sort') || ''
  const order = sp.get('order') || ''

  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [destSearch, setDestSearch] = useState('')

  const [newOpen, setNewOpen] = useState(sp.get('new') === '1')
  const [bulkOpen, setBulkOpen] = useState(false)
  const [destOpen, setDestOpen] = useState(false)
  const [actionsLink, setActionsLink] = useState<LinkRow | null>(null)
  const [editLink, setEditLink] = useState<LinkRow | null>(null)
  const [expandedAccounts, setExpandedAccounts] = useState<Record<string, boolean>>({})
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams()
      if (platform && platform !== 'all') q.set('platform', platform)
      if (account) q.set('account', account)
      if (destination && destination !== 'all') q.set('destination', destination)
      if (preset && preset !== 'all') q.set('preset', preset)
      if (sort) q.set('sort', sort)
      if (order) q.set('order', order)
      const dash = await api<Dashboard>(`/admin/api/dashboard?${q.toString()}`)
      setData(dash)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [platform, account, destination, preset, sort, order])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setSelectedIds([])
  }, [platform, account, destination, preset, sort, order])

  const visibleIds = useMemo(() => (data?.links || []).map((r) => r.id), [data?.links])
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id))
  const someVisibleSelected = visibleIds.some((id) => selectedIds.includes(id))

  function toggleSelect(id: string) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  function toggleSelectAllVisible() {
    if (allVisibleSelected) {
      setSelectedIds((prev) => prev.filter((id) => !visibleIds.includes(id)))
    } else {
      setSelectedIds((prev) => [...new Set([...prev, ...visibleIds])])
    }
  }

  function setFilter(next: Record<string, string>) {
    const merged = {
      platform,
      account,
      destination,
      preset,
      sort,
      order,
      ...next,
    }
    const n = new URLSearchParams()
    if (merged.platform && merged.platform !== 'all') n.set('platform', merged.platform)
    if (merged.account) n.set('account', merged.account)
    if (merged.destination && merged.destination !== 'all') n.set('destination', merged.destination)
    if (merged.preset && merged.preset !== 'all') n.set('preset', merged.preset)
    if (merged.sort) n.set('sort', merged.sort)
    if (merged.order) n.set('order', merged.order)
    setSp(n, { replace: true })
  }

  function toggleSort(col: string) {
    if (sort === col) {
      setFilter({ sort: col, order: order === 'desc' ? 'asc' : 'desc' })
    } else {
      setFilter({ sort: col, order: 'desc' })
    }
  }

  const destinationItems = useMemo(() => {
    const items = data?.destination_filters || []
    const q = destSearch.trim().toLowerCase()
    if (!q) return items
    return items.filter((it) => {
      if (it.id === 'all') return true
      return it.name.toLowerCase().includes(q) || it.id.toLowerCase().includes(q)
    })
  }, [data?.destination_filters, destSearch])

  return (
    <div>
      <div className="row between wrap" style={{ gap: '1rem', alignItems: 'flex-start' }}>
        <div>
          <h1 className="page-title">Короткие ссылки</h1>
          <p className="muted small">
            «Всего» / «Сегодня» — за всё время и сутки UTC. «За период» — по фильтру ниже.
          </p>
        </div>
        <div className="admin-actions">
          <button type="button" className="btn btn-primary" onClick={() => setNewOpen(true)}>
            + Создать ссылку
          </button>
          <button type="button" className="btn" onClick={() => setBulkOpen(true)}>
            Массовое создание
          </button>
          <button
            type="button"
            className="btn"
            disabled={!selectedIds.length}
            title={selectedIds.length ? undefined : 'Выберите ссылки в таблице'}
            onClick={() => setDestOpen(true)}
          >
            Действия{selectedIds.length ? ` (${selectedIds.length})` : ''}
          </button>
        </div>
      </div>

      {error ? <div className="error-box" style={{ marginTop: '1rem' }}>{error}</div> : null}
      {loading && !data ? <div className="loading">Загрузка…</div> : null}

      {data ? (
        <div className="links-layout">
          <aside className="sidebar" aria-label="Фильтр по цели">
            <input
              className="input"
              type="search"
              placeholder="Поиск целей"
              value={destSearch}
              onChange={(e) => setDestSearch(e.target.value)}
              style={{ marginBottom: '0.65rem' }}
            />
            <nav className="stack" style={{ gap: '0.15rem', maxHeight: '70vh', overflow: 'auto' }}>
              {destinationItems.map((it) => {
                const active =
                  destination === it.id || (it.id === 'all' && (!destination || destination === 'all'))
                return (
                  <button
                    key={it.id}
                    type="button"
                    className={`sidebar-item${active ? ' active' : ''}`}
                    title={it.id === 'all' ? undefined : it.id}
                    onClick={() => setFilter({ destination: it.id })}
                  >
                    {it.id === 'all' ? (
                      <span
                        className="ring"
                        aria-hidden
                        style={{
                          background: active ? 'var(--accent)' : 'var(--surface-2)',
                          color: active ? '#fff' : 'var(--muted)',
                        }}
                      >
                        ∗
                      </span>
                    ) : (
                      <Avatar
                        url={it.icon_url}
                        fallbackUrl={it.platform_icon_url}
                        fallbackUrls={it.icon_fallbacks}
                        name={it.name}
                      />
                    )}
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {it.name}
                    </span>
                    <span className="sidebar-item__count">{it.count}</span>
                  </button>
                )
              })}
              {!destinationItems.length ? <p className="muted small">Нет целей</p> : null}
            </nav>
          </aside>

          <div className="stack">
            <div className="pills">
              {data.platform_filters.map((pl) => (
                <button
                  key={pl.id}
                  type="button"
                  className={`pill${platform === pl.id ? ' active' : ''}`}
                  onClick={() => setFilter({ platform: pl.id })}
                >
                  {pl.color ? <span className="pill__dot" style={{ background: pl.color }} /> : null}
                  {pl.label}
                </button>
              ))}
            </div>
            <div className="pills">
              {(
                [
                  ['today', 'Сегодня'],
                  ['week', 'Неделя'],
                  ['all', 'Всё время'],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={`pill${preset === id ? ' active' : ''}`}
                  onClick={() => setFilter({ preset: id })}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="kpi-grid">
              <div className="kpi-card">
                <span className="kpi-card__num">{data.period_total}</span>
                <span className="kpi-card__lbl">кликов за период</span>
                <div className="muted small">{data.period_label}</div>
              </div>
              <div className="kpi-card kpi-card--accent">
                <span className="kpi-card__num">{data.period_uniques}</span>
                <span className="kpi-card__lbl">уникальных</span>
              </div>
            </div>

            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault()
                const fd = new FormData(e.currentTarget)
                setFilter({ account: String(fd.get('account') || '') })
              }}
            >
              <input
                className="input"
                name="account"
                type="search"
                placeholder="Поиск по аккаунту"
                defaultValue={account}
              />
              <button className="btn" type="submit">
                Найти
              </button>
            </form>

            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: '2.25rem' }} onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={allVisibleSelected}
                        ref={(el) => {
                          if (el) el.indeterminate = someVisibleSelected && !allVisibleSelected
                        }}
                        onChange={toggleSelectAllVisible}
                        aria-label="Выбрать все на странице"
                      />
                    </th>
                    <th>Название</th>
                    <th>С какого аккаунта(ов)</th>
                    <th>Цель</th>
                    <th className="num">
                      <button type="button" className="btn btn-ghost" onClick={() => toggleSort('total')}>
                        Всего
                      </button>
                    </th>
                    <th className="num">
                      <button type="button" className="btn btn-ghost" onClick={() => toggleSort('today')}>
                        Сегодня
                      </button>
                    </th>
                    <th className="num">Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {data.links.map((row) => (
                    <tr key={row.id} onClick={() => nav(`/admin/links/${row.id}/stats`)}>
                      <td onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(row.id)}
                          onChange={() => toggleSelect(row.id)}
                          aria-label="Выбрать ссылку"
                        />
                      </td>
                      <td>{row.title?.trim() || '—'}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <AccountCell
                          display={row.account_display}
                          platformIconUrl={row.platform_icon_url}
                          platformLabel={row.platform_label}
                          expanded={!!expandedAccounts[row.id]}
                          onToggle={() =>
                            setExpandedAccounts((prev) => ({
                              ...prev,
                              [row.id]: !prev[row.id],
                            }))
                          }
                        />
                      </td>
                      <td
                        className="muted small"
                        style={{
                          maxWidth: '18rem',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                        title={row.destination_url}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <span className="row" style={{ gap: '0.45rem', minWidth: 0 }}>
                          <Avatar
                            url={row.destination_icon_url}
                            fallbackUrl={row.destination_icon_fallback_url}
                            fallbackUrls={row.destination_icon_fallbacks}
                            name={row.destination_url}
                          />
                          <a
                            href={row.destination_url}
                            target="_blank"
                            rel="noreferrer"
                            style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          >
                            {row.destination_url}
                          </a>
                        </span>
                      </td>
                      <td className="num">{row.total}</td>
                      <td className="num">{row.today}</td>
                      <td className="num" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="btn"
                          onClick={() => setActionsLink(row)}
                          aria-label="Действия"
                        >
                          ⋯
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!data.links.length ? (
                    <tr style={{ cursor: 'default' }}>
                      <td colSpan={7} className="muted">
                        Нет ссылок по фильтру
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}

      <NewLinkModal
        open={newOpen}
        onClose={() => {
          setNewOpen(false)
          if (sp.get('new')) {
            sp.delete('new')
            setSp(sp, { replace: true })
          }
        }}
        onCreated={(ids) => {
          if (ids.length === 1) {
            nav(`/admin/links/${ids[0]}/stats`)
          } else {
            setNewOpen(false)
            if (sp.get('new')) {
              sp.delete('new')
              setSp(sp, { replace: true })
            }
            void load()
          }
        }}
      />
      <BulkModal
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onDone={() => {
          setBulkOpen(false)
          void load()
        }}
      />
      <BulkActionsModal
        open={destOpen}
        linkIds={selectedIds}
        onClose={() => setDestOpen(false)}
        onDone={() => {
          setDestOpen(false)
          setSelectedIds([])
          void load()
        }}
      />
      <LinkActionsModal
        open={!!actionsLink}
        link={actionsLink}
        onClose={() => setActionsLink(null)}
        onEdit={() => {
          if (!actionsLink) return
          setEditLink(actionsLink)
          setActionsLink(null)
        }}
        onDeleted={() => {
          setActionsLink(null)
          void load()
        }}
      />
      <EditLinkModal
        open={!!editLink}
        link={editLink}
        onClose={() => setEditLink(null)}
        onSaved={() => {
          setEditLink(null)
          void load()
        }}
      />
    </div>
  )
}

function LinkActionsModal({
  open,
  link,
  onClose,
  onEdit,
  onDeleted,
}: {
  open: boolean
  link: LinkRow | null
  onClose: () => void
  onEdit: () => void
  onDeleted: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) setError(null)
  }, [open])

  async function onDelete() {
    if (!link) return
    if (!confirm('Удалить ссылку и всю статистику?')) return
    setBusy(true)
    setError(null)
    try {
      await api(`/admin/api/links/${link.id}`, { method: 'DELETE' })
      onDeleted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  const title = link?.title?.trim() || link?.account_display || link?.slug || 'Ссылка'

  return (
    <Modal open={open} title="Действия" onClose={onClose}>
      <div className="stack">
        <p className="muted small" style={{ margin: 0 }}>
          {title}
        </p>
        {error ? <div className="error-box">{error}</div> : null}
        <button type="button" className="btn btn-primary" onClick={onEdit} disabled={busy}>
          Изменить
        </button>
        <button type="button" className="btn btn-danger" onClick={() => void onDelete()} disabled={busy}>
          Удалить
        </button>
      </div>
    </Modal>
  )
}

function EditLinkModal({
  open,
  link,
  onClose,
  onSaved,
}: {
  open: boolean
  link: LinkRow | null
  onClose: () => void
  onSaved: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!link) return
    setBusy(true)
    setError(null)
    const fd = new FormData(e.currentTarget)
    try {
      await api(`/admin/api/links/${link.id}`, {
        method: 'PATCH',
        json: {
          destination_url: fd.get('destination_url'),
          title: fd.get('title'),
          label: fd.get('label'),
        },
      })
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  if (!link) return null

  return (
    <Modal open={open} title="Правка ссылки" onClose={onClose}>
      <form className="stack" onSubmit={onSubmit} key={link.id}>
        {error ? <div className="error-box">{error}</div> : null}
        <label className="field-label">
          Цель
          <input className="input" name="destination_url" defaultValue={link.destination_url} required />
        </label>
        <label className="field-label">
          Название
          <input className="input" name="title" defaultValue={link.title || ''} placeholder="Как отображать в таблице" />
        </label>
        <label className="field-label">
          С какого аккаунта(ов)
          <textarea
            className="input textarea"
            name="label"
            defaultValue={link.label || ''}
            rows={3}
            placeholder="https://instagram.com/one, https://t.me/two"
          />
          <span className="muted small">
            Несколько аккаунтов — через запятую или с новой строки. Разные платформы разойдутся на
            отдельные ссылки
          </span>
        </label>
        <button className="btn btn-primary" disabled={busy} type="submit">
          Сохранить
        </button>
      </form>
    </Modal>
  )
}

function NewLinkModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (ids: string[]) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const fd = new FormData(e.currentTarget)
    try {
      const res = await api<{ link: LinkRow; links?: LinkRow[]; created?: number }>('/admin/api/links', {
        method: 'POST',
        json: {
          destination_url: fd.get('destination_url'),
          title: fd.get('title') || null,
          label: fd.get('label') || null,
        },
      })
      const ids = (res.links?.length ? res.links : [res.link]).map((l) => l.id)
      onCreated(ids)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} title="Новая ссылка" onClose={onClose}>
      <form className="stack" onSubmit={onSubmit}>
        {error ? <div className="error-box">{error}</div> : null}
        <label className="field-label">
          Цель (URL)
          <input className="input" name="destination_url" type="url" required placeholder="https://" />
        </label>
        <label className="field-label">
          Название
          <input className="input" name="title" placeholder="Как отображать в таблице" />
        </label>
        <label className="field-label">
          С какого аккаунта(ов)
          <textarea
            className="input textarea"
            name="label"
            rows={3}
            placeholder="https://instagram.com/one, https://t.me/two"
          />
          <span className="muted small">
            Несколько аккаунтов — через запятую или с новой строки. Разные платформы разойдутся на
            отдельные ссылки
          </span>
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          Создать
        </button>
      </form>
    </Modal>
  )
}

function BulkModal({
  open,
  onClose,
  onDone,
}: {
  open: boolean
  onClose: () => void
  onDone: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const fd = new FormData(e.currentTarget)
    try {
      await api('/admin/api/links/bulk', {
        method: 'POST',
        json: {
          destination_url: fd.get('destination_url'),
          labels: fd.get('labels'),
        },
      })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} title="Массовое создание" onClose={onClose} wide>
      <form className="stack" onSubmit={onSubmit}>
        {error ? <div className="error-box">{error}</div> : null}
        <label className="field-label">
          Общая цель (URL)
          <input className="input" name="destination_url" type="url" required />
        </label>
        <label className="field-label">
          Аккаунты
          <textarea
            className="input textarea"
            name="labels"
            required
            placeholder="По одному на строку или через запятую"
          />
          <span className="muted small">Каждый аккаунт — отдельная ссылка. Разделитель: новая строка или запятая</span>
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          Создать
        </button>
      </form>
    </Modal>
  )
}

function BulkActionsModal({
  open,
  linkIds,
  onClose,
  onDone,
}: {
  open: boolean
  linkIds: string[]
  onClose: () => void
  onDone: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<'menu' | 'destination' | 'delete'>('menu')

  useEffect(() => {
    if (open) {
      setMode('menu')
      setError(null)
      setBusy(false)
    }
  }, [open])

  async function onChangeDestination(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!linkIds.length) return
    setBusy(true)
    setError(null)
    const fd = new FormData(e.currentTarget)
    try {
      await api('/admin/api/links/bulk-destination', {
        method: 'POST',
        json: { destination_url: fd.get('destination_url'), link_ids: linkIds },
      })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  async function onDelete() {
    if (!linkIds.length) return
    setBusy(true)
    setError(null)
    try {
      await api('/admin/api/links/bulk-delete', {
        method: 'POST',
        json: { link_ids: linkIds },
      })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  const title =
    mode === 'destination'
      ? 'Сменить цель'
      : mode === 'delete'
        ? 'Удалить ссылки'
        : 'Действия'

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <div className="stack">
        {error ? <div className="error-box">{error}</div> : null}
        <p className="muted small">Выбрано ссылок: {linkIds.length}</p>

        {mode === 'menu' ? (
          <div className="stack">
            <button type="button" className="btn" onClick={() => setMode('destination')}>
              Сменить цель
            </button>
            <button type="button" className="btn btn-danger" onClick={() => setMode('delete')}>
              Удалить
            </button>
          </div>
        ) : null}

        {mode === 'destination' ? (
          <form className="stack" onSubmit={onChangeDestination}>
            <label className="field-label">
              Новый URL цели
              <input className="input" name="destination_url" type="url" required placeholder="https://" />
            </label>
            <div className="row" style={{ gap: '0.5rem' }}>
              <button type="button" className="btn" onClick={() => setMode('menu')} disabled={busy}>
                Назад
              </button>
              <button className="btn btn-primary" type="submit" disabled={busy || !linkIds.length}>
                Обновить цель
              </button>
            </div>
          </form>
        ) : null}

        {mode === 'delete' ? (
          <div className="stack">
            <p>
              Удалить {linkIds.length} ссылк
              {linkIds.length === 1 ? 'у' : linkIds.length < 5 ? 'и' : 'ок'} вместе со статистикой
              кликов? Это нельзя отменить.
            </p>
            <div className="row" style={{ gap: '0.5rem' }}>
              <button type="button" className="btn" onClick={() => setMode('menu')} disabled={busy}>
                Назад
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => void onDelete()}
                disabled={busy || !linkIds.length}
              >
                Удалить
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  )
}
