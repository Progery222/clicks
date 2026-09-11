import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError, type Dashboard, type LinkRow } from '../api'
import { Avatar, Modal } from '../components'

export function LinksPage() {
  const [sp, setSp] = useSearchParams()
  const nav = useNavigate()
  const platform = sp.get('platform') || 'all'
  const account = sp.get('account') || ''
  const preset = sp.get('preset') || 'all'
  const sort = sp.get('sort') || ''
  const order = sp.get('order') || ''

  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const [newOpen, setNewOpen] = useState(sp.get('new') === '1')
  const [bulkOpen, setBulkOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [destOpen, setDestOpen] = useState(false)
  const [actionsLink, setActionsLink] = useState<LinkRow | null>(null)
  const [editLink, setEditLink] = useState<LinkRow | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams()
      if (platform) q.set('platform', platform)
      if (account) q.set('account', account)
      if (preset && preset !== 'custom') q.set('preset', preset === 'all' ? '' : preset)
      if (preset === 'all') {
        /* default */
      } else if (preset) q.set('preset', preset)
      if (sort) q.set('sort', sort)
      if (order) q.set('order', order)
      ;[...q.keys()].forEach((k) => {
        if (!q.get(k)) q.delete(k)
      })
      if (preset && preset !== 'all') q.set('preset', preset)
      const dash = await api<Dashboard>(`/admin/api/dashboard?${q.toString()}`)
      setData(dash)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [platform, account, preset, sort, order])

  useEffect(() => {
    void load()
  }, [load])

  function setFilter(next: Record<string, string>) {
    const merged = {
      platform,
      account,
      preset,
      sort,
      order,
      ...next,
    }
    const n = new URLSearchParams()
    if (merged.platform && merged.platform !== 'all') n.set('platform', merged.platform)
    if (merged.account) n.set('account', merged.account)
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

  const exportQs = data?.filter_qs || ''

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
          <button type="button" className="btn" onClick={() => setImportOpen(true)}>
            Импорт CSV
          </button>
          <button type="button" className="btn" onClick={() => setDestOpen(true)}>
            Сменить цель
          </button>
          <a className="btn" href={`/admin/export/links.csv${exportQs}`}>
            Ссылки CSV
          </a>
          <a className="btn" href={`/admin/export/clicks.csv${exportQs}`}>
            Клики CSV
          </a>
        </div>
      </div>

      {error ? <div className="error-box" style={{ marginTop: '1rem' }}>{error}</div> : null}
      {loading && !data ? <div className="loading">Загрузка…</div> : null}

      {data ? (
        <div className="stack" style={{ marginTop: '1rem' }}>
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
                    <th>Название</th>
                    <th>Платф.</th>
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
                      <td>{row.title?.trim() || '—'}</td>
                      <td>
                        {row.platform ? (
                          <span className="row" style={{ gap: '0.35rem' }}>
                            <span className="pill__dot" style={{ background: row.platform_color }} />
                            {row.platform_label}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>
                        <span className="row" style={{ gap: '0.45rem' }}>
                          <Avatar url={row.account_avatar_url} name={row.account_display} />
                          <span>{row.account_display}</span>
                        </span>
                      </td>
                      <td
                        className="muted small"
                        style={{ maxWidth: '16rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={row.destination_url}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <a href={row.destination_url} target="_blank" rel="noreferrer">
                          {row.destination_url}
                        </a>
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
        onCreated={(id) => nav(`/admin/links/${id}/stats`)}
      />
      <BulkModal
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onDone={() => {
          setBulkOpen(false)
          void load()
        }}
      />
      <ImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onDone={() => {
          setImportOpen(false)
          void load()
        }}
      />
      <DestModal open={destOpen} onClose={() => setDestOpen(false)} onDone={() => { setDestOpen(false); void load() }} />
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
          <input className="input" name="label" defaultValue={link.label || ''} />
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
  onCreated: (id: string) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const fd = new FormData(e.currentTarget)
    try {
      const res = await api<{ link: LinkRow }>('/admin/api/links', {
        method: 'POST',
        json: {
          destination_url: fd.get('destination_url'),
          title: fd.get('title') || null,
          label: fd.get('label') || null,
        },
      })
      onCreated(res.link.id)
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
          <input className="input" name="label" />
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
          Аккаунты (по одному на строку)
          <textarea className="input textarea" name="labels" required />
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          Создать
        </button>
      </form>
    </Modal>
  )
}

function ImportModal({
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
      await api('/admin/api/links/import-csv', { method: 'POST', body: fd })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} title="Импорт CSV" onClose={onClose}>
      <form className="stack" onSubmit={onSubmit}>
        {error ? <div className="error-box">{error}</div> : null}
        <label className="field-label">
          CSV файл
          <input className="input" name="file" type="file" accept=".csv,text/csv" required />
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          Импортировать
        </button>
      </form>
    </Modal>
  )
}

function DestModal({
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
  const [items, setItems] = useState<{ id: string; display: string }[]>([])
  const [selected, setSelected] = useState<string[]>([])

  useEffect(() => {
    if (!open) return
    void api<{ items: { id: string; display: string }[] }>('/admin/api/links-picker').then((r) =>
      setItems(r.items),
    )
  }, [open])

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const fd = new FormData(e.currentTarget)
    try {
      await api('/admin/api/links/bulk-destination', {
        method: 'POST',
        json: { destination_url: fd.get('destination_url'), link_ids: selected },
      })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} title="Сменить цель" onClose={onClose} wide>
      <form className="stack" onSubmit={onSubmit}>
        {error ? <div className="error-box">{error}</div> : null}
        <label className="field-label">
          Новый URL
          <input className="input" name="destination_url" type="url" required />
        </label>
        <div className="stack" style={{ maxHeight: '12rem', overflow: 'auto' }}>
          {items.map((it) => (
            <label key={it.id} className="row" style={{ gap: '0.5rem' }}>
              <input
                type="checkbox"
                checked={selected.includes(it.id)}
                onChange={(e) => {
                  setSelected((prev) =>
                    e.target.checked ? [...prev, it.id] : prev.filter((x) => x !== it.id),
                  )
                }}
              />
              <span>{it.display}</span>
            </label>
          ))}
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy || !selected.length}>
          Обновить ({selected.length})
        </button>
      </form>
    </Modal>
  )
}
