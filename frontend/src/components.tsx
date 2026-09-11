import { NavLink, useNavigate } from 'react-router-dom'
import { useEffect, useState, type ReactNode } from 'react'
import { useAuth } from './auth'

export function Shell({ children }: { children: ReactNode }) {
  const { me, theme, cycleTheme, logout } = useAuth()
  const nav = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  async function onLogout() {
    await logout()
    nav('/admin/login')
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="row" style={{ gap: '0.75rem' }}>
          <a className="brand" href="/admin">
            <span className="brand__mark" aria-hidden />
            <span>Bio links</span>
          </a>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ display: 'none' }}
            aria-label="Меню"
            onClick={() => setMenuOpen((v) => !v)}
            id="nav-burger"
          >
            ☰
          </button>
        </div>
        <nav className={`nav${menuOpen ? ' open' : ''}`} aria-label="Разделы">
          <NavLink to="/admin" end onClick={() => setMenuOpen(false)}>
            Ссылки
          </NavLink>
          <NavLink to="/indicators" onClick={() => setMenuOpen(false)}>
            Показатели
          </NavLink>
        </nav>
        <div className="topbar__actions">
          <button type="button" className="btn btn-ghost" onClick={cycleTheme} title="Тема">
            {theme === 'dark' ? 'Светлая' : 'Тёмная'}
          </button>
          {me?.admin ? (
            <button type="button" className="btn" onClick={onLogout}>
              Выход
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-ghost burger-only"
            aria-label="Меню"
            onClick={() => setMenuOpen((v) => !v)}
          >
            ☰
          </button>
        </div>
      </header>
      <main className="main">{children}</main>
      <style>{`
        @media (max-width: 900px) {
          .burger-only { display: inline-flex !important; }
          #nav-burger { display: inline-flex !important; }
        }
        @media (min-width: 901px) {
          .burger-only { display: none !important; }
        }
      `}</style>
    </div>
  )
}

export function Modal({
  open,
  title,
  onClose,
  children,
  wide,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  if (!open) return null
  return (
    <div className="modal-root" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal-backdrop" onClick={onClose} />
      <div className={`modal-panel${wide ? ' modal-panel--wide' : ''}`}>
        <div className="modal-head">
          <h2 className="modal-title">{title}</h2>
          <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function BarChart({ items, limit = 8 }: { items: { label: string; count: number; pct: number; color?: string }[]; limit?: number }) {
  const [showAll, setShowAll] = useState(false)
  const visible = showAll ? items : items.slice(0, limit)
  if (!items.length) return <p className="muted small">Нет данных</p>
  return (
    <div className="stack">
      <div className="bar-chart">
        {visible.map((it) => (
          <div className="bar-chart__row" key={it.label}>
            <div className="bar-chart__label" title={it.label}>
              {it.label}
            </div>
            <div className="bar-chart__track">
              <div
                className="bar-chart__fill"
                style={{ width: `${it.pct}%`, background: it.color || undefined }}
              />
            </div>
            <div className="bar-chart__value">{it.count}</div>
          </div>
        ))}
      </div>
      {items.length > limit ? (
        <button type="button" className="btn btn-ghost" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Свернуть' : 'Смотреть все'}
        </button>
      ) : null}
    </div>
  )
}

export function Avatar({
  url,
  fallbackUrl,
  fallbackUrls,
  name,
  size = 'sm',
}: {
  url?: string | null
  fallbackUrl?: string | null
  fallbackUrls?: (string | null | undefined)[]
  name: string
  size?: 'sm' | 'lg'
}) {
  const letter = (name || '?').slice(0, 1).toUpperCase()
  const chain = (() => {
    const xs = [url, fallbackUrl, ...(fallbackUrls || [])].filter(
      (x): x is string => typeof x === 'string' && !!x.trim(),
    )
    return [...new Set(xs)]
  })()
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    setIdx(0)
  }, [chain.join('\0')])

  const src = chain[idx] ?? null

  if (src) {
    return (
      <img
        className={`avatar${size === 'lg' ? ' avatar--lg' : ''}`}
        src={src}
        alt=""
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setIdx((i) => i + 1)}
      />
    )
  }
  return (
    <span className={`avatar avatar-letter${size === 'lg' ? ' avatar--lg' : ''}`} aria-hidden>
      {letter}
    </span>
  )
}
