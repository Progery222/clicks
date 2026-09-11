import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError, type Profile } from '../api'
import { Modal } from '../components'

export function ProfilesPage() {
  const [profiles, setProfiles] = useState<(Profile & { count?: number })[]>([])
  const [palette, setPalette] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [edit, setEdit] = useState<Profile | null>(null)

  async function load() {
    try {
      const res = await api<{ profiles: (Profile & { count?: number })[]; palette: string[] }>(
        '/admin/api/profiles',
      )
      setProfiles(res.profiles)
      setPalette(res.palette || [])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function remove(id: string, name: string) {
    if (!confirm(`Удалить профиль «${name}»? Ссылки останутся без профиля.`)) return
    await api(`/admin/api/profiles/${id}`, { method: 'DELETE' })
    await load()
  }

  return (
    <div>
      <div className="row between wrap">
        <div>
          <h1 className="page-title">Профили</h1>
          <p className="muted small">Группировка ссылок по проектам / аккаунтам</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setCreateOpen(true)}>
          + Профиль
        </button>
      </div>
      {error ? <div className="error-box" style={{ marginTop: '1rem' }}>{error}</div> : null}
      <div className="table-wrap" style={{ marginTop: '1rem' }}>
        <table className="table">
          <thead>
            <tr>
              <th>Имя</th>
              <th className="num">Ссылок</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {profiles.map((p) => (
              <tr key={p.id} style={{ cursor: 'default' }}>
                <td>
                  <span className="row" style={{ gap: '0.45rem' }}>
                    <span className="ring" style={{ background: p.color }}>
                      {p.name.slice(0, 1)}
                    </span>
                    {p.name}
                  </span>
                </td>
                <td className="num">{p.count ?? 0}</td>
                <td>
                  <div className="row" style={{ justifyContent: 'flex-end' }}>
                    <button type="button" className="btn btn-ghost" onClick={() => setEdit(p)}>
                      Изменить
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() => void remove(p.id, p.name)}
                    >
                      Удалить
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ProfileFormModal
        open={createOpen}
        title="Новый профиль"
        palette={palette}
        onClose={() => setCreateOpen(false)}
        onSubmit={async (name, color) => {
          await api('/admin/api/profiles', { method: 'POST', json: { name, color } })
          setCreateOpen(false)
          await load()
        }}
      />
      <ProfileFormModal
        open={!!edit}
        title="Редактировать профиль"
        palette={palette}
        initial={edit || undefined}
        onClose={() => setEdit(null)}
        onSubmit={async (name, color) => {
          if (!edit) return
          await api(`/admin/api/profiles/${edit.id}`, { method: 'PATCH', json: { name, color } })
          setEdit(null)
          await load()
        }}
      />
    </div>
  )
}

function ProfileFormModal({
  open,
  title,
  palette,
  initial,
  onClose,
  onSubmit,
}: {
  open: boolean
  title: string
  palette: string[]
  initial?: Profile
  onClose: () => void
  onSubmit: (name: string, color: string) => Promise<void>
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function handle(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const fd = new FormData(e.currentTarget)
    try {
      await onSubmit(String(fd.get('name') || ''), String(fd.get('color') || palette[0] || '#0d9488'))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} title={title} onClose={onClose}>
      <form className="stack" onSubmit={handle}>
        {error ? <div className="error-box">{error}</div> : null}
        <label className="field-label">
          Имя
          <input className="input" name="name" required defaultValue={initial?.name || ''} />
        </label>
        <label className="field-label">
          Цвет
          <input
            className="input"
            name="color"
            type="color"
            defaultValue={initial?.color || palette[0] || '#0d9488'}
          />
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          Сохранить
        </button>
      </form>
    </Modal>
  )
}
