import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError, setCsrf } from '../api'
import { useAuth } from '../auth'

export function LoginPage() {
  const { me, loading, refresh, theme, cycleTheme } = useAuth()
  const nav = useNavigate()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!loading && me?.admin) return <Navigate to="/admin" replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await api<{ ok: boolean; csrf_token?: string; error?: string; blocked?: boolean }>(
        '/admin/api/auth/login',
        { method: 'POST', json: { password } },
      )
      if (res.csrf_token) setCsrf(res.csrf_token)
      await refresh()
      nav('/admin')
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body as { error?: string; blocked?: boolean } | null
        setError(body?.error || err.message)
      } else {
        setError('Ошибка входа')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <div className="card login-card stack">
        <div className="row between">
          <div>
            <div className="brand" style={{ marginBottom: '0.5rem' }}>
              <span className="brand__mark" />
              <span>Bio links</span>
            </div>
            <h1 className="page-title" style={{ fontSize: '1.35rem' }}>
              Вход
            </h1>
            <p className="muted small">Панель управления короткими ссылками</p>
          </div>
          <button type="button" className="btn btn-ghost" onClick={cycleTheme}>
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </div>
        {me?.blocked || error ? <div className="error-box">{error || me?.block_message}</div> : null}
        <form className="stack" onSubmit={onSubmit}>
          <label className="field-label">
            Пароль
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={!!me?.blocked}
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy || !!me?.blocked}>
            {busy ? 'Вход…' : 'Войти'}
          </button>
        </form>
      </div>
    </div>
  )
}

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return <div className="loading">Загрузка…</div>
  if (!me?.admin) return <Navigate to="/admin/login" replace />
  return <Shell>{children}</Shell>
}
