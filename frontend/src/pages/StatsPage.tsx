import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, type LinkStats, type Profile } from '../api'
import { Avatar, BarChart, Modal } from '../components'

export function StatsPage() {
  const { linkId = '' } = useParams()
  const [sp, setSp] = useSearchParams()
  const nav = useNavigate()
  const preset = sp.get('preset') || 'all'
  const [data, setData] = useState<LinkStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [daysOpen, setDaysOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [profiles, setProfiles] = useState<Profile[]>([])

  const load = useCallback(async () => {
    setError(null)
    try {
      const q = new URLSearchParams()
      if (preset && preset !== 'all') q.set('preset', preset)
      const from = sp.get('from')
      const to = sp.get('to')
      if (from) q.set('from', from)
      if (to) q.set('to', to)
      const res = await api<LinkStats>(`/admin/api/links/${linkId}/stats?${q}`)
      setData(res)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    }
  }, [linkId, preset, sp])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void api<{ profiles: Profile[] }>('/admin/api/profiles').then((r) => setProfiles(r.profiles))
  }, [])

  async function clearClicks() {
    if (!confirm('Очистить статистику кликов по этой ссылке?')) return
    await api(`/admin/api/links/${linkId}/clicks`, { method: 'DELETE' })
    await load()
  }

  async function deleteLink() {
    if (!confirm('Удалить ссылку и всю статистику?')) return
    await api(`/admin/api/links/${linkId}`, { method: 'DELETE' })
    nav('/admin')
  }

  if (error) return <div className="error-box">{error}</div>
  if (!data) return <div className="loading">Загрузка…</div>

  const link = data.link

  return (
    <div className="stack">
      <div className="row between wrap" style={{ alignItems: 'flex-start' }}>
        <div className="row" style={{ gap: '0.85rem', alignItems: 'center' }}>
          <Avatar url={link.account_avatar_url} name={link.account_display || link.slug} size="lg" />
          <div>
            <h1 className="page-title">{link.display_name || link.title || link.label || link.slug}</h1>
            <p className="muted small">
              Короткая:{' '}
              <a href={data.short_url} target="_blank" rel="noreferrer">
                {data.short_url}
              </a>
            </p>
            <p className="muted small" style={{ wordBreak: 'break-all' }}>
              Цель:{' '}
              <a href={link.destination_url} target="_blank" rel="noreferrer">
                {link.destination_url}
              </a>
            </p>
          </div>
        </div>
        <div className="admin-actions">
          <button type="button" className="btn" onClick={() => setEditOpen(true)}>
            Правка
          </button>
          <Link className="btn" to="/admin">
            Все ссылки
          </Link>
          <button type="button" className="btn btn-danger" onClick={() => void deleteLink()}>
            Удалить
          </button>
        </div>
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
            onClick={() => {
              const n = new URLSearchParams()
              if (id !== 'all') n.set('preset', id)
              setSp(n, { replace: true })
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="kpi-grid">
        <div className="kpi-card">
          <span className="kpi-card__num">{data.total}</span>
          <span className="kpi-card__lbl">кликов</span>
        </div>
        <div className="kpi-card kpi-card--accent">
          <span className="kpi-card__num">{data.uniques}</span>
          <span className="kpi-card__lbl">уникальных</span>
        </div>
      </div>

      <div className="card stack">
        <button type="button" className="btn" onClick={() => setDaysOpen((v) => !v)}>
          Клики по дням {daysOpen ? '▾' : '▸'}
        </button>
        {daysOpen ? <BarChart items={data.charts.clicks_by_day} limit={14} /> : null}
      </div>

      <div className="charts-grid">
        <div className="card">
          <h2 className="section-title" style={{ marginTop: 0 }}>
            Топ стран
          </h2>
          <BarChart items={data.charts.countries} limit={3} />
        </div>
        <div className="card">
          <h2 className="section-title" style={{ marginTop: 0 }}>
            ОС
          </h2>
          <BarChart items={data.charts.os} limit={3} />
        </div>
        <div className="card">
          <h2 className="section-title" style={{ marginTop: 0 }}>
            Устройства
          </h2>
          <BarChart items={data.charts.devices} limit={3} />
        </div>
      </div>

      <div className="card stack">
        <button type="button" className="btn btn-danger" onClick={() => void clearClicks()}>
          Очистить статистику кликов
        </button>
        <p className="muted small">Безвозвратно удаляются все клики по этой ссылке.</p>
      </div>

      <EditLinkModal
        open={editOpen}
        link={link}
        profiles={profiles}
        onClose={() => setEditOpen(false)}
        onSaved={async () => {
          setEditOpen(false)
          await load()
        }}
      />
    </div>
  )
}

function EditLinkModal({
  open,
  link,
  profiles,
  onClose,
  onSaved,
}: {
  open: boolean
  link: LinkStats['link']
  profiles: Profile[]
  onClose: () => void
  onSaved: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
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
          profile_id: fd.get('profile_id') || '',
        },
      })
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} title="Правка ссылки" onClose={onClose}>
      <form className="stack" onSubmit={onSubmit}>
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
          Метка
          <input className="input" name="label" defaultValue={link.label || ''} />
        </label>
        <label className="field-label">
          Профиль
          <select className="input" name="profile_id" defaultValue={link.profile_id || ''}>
            <option value="">Без профиля</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <button className="btn btn-primary" disabled={busy} type="submit">
          Сохранить
        </button>
      </form>
    </Modal>
  )
}
