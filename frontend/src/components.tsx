import { NavLink, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useAuth } from './auth'

function IconMoon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 14.5A8.5 8.5 0 1 1 9.5 3a7 7 0 0 0 11.5 11.5z" />
    </svg>
  )
}

function IconSun() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  )
}

function IconLogout() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  )
}

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
          <button
            type="button"
            className="btn btn-ghost btn-icon"
            onClick={cycleTheme}
            title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
            aria-label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
          >
            {theme === 'dark' ? <IconSun /> : <IconMoon />}
          </button>
          {me?.admin ? (
            <button
              type="button"
              className="btn btn-icon"
              onClick={onLogout}
              title="Выход"
              aria-label="Выйти"
            >
              <IconLogout />
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

export function PlatformFilter({
  options,
  value,
  onChange,
}: {
  options: { id: string; label: string; color: string | null }[]
  /** ``all`` или id через запятую */
  value: string
  onChange: (next: string) => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const items = useMemo(() => options.filter((o) => o.id !== 'all'), [options])
  const allIds = useMemo(() => items.map((o) => o.id), [items])

  const selected = useMemo(() => {
    if (!value || value === 'all') return new Set(allIds)
    return new Set(value.split(',').map((s) => s.trim()).filter(Boolean))
  }, [value, allIds])

  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id))
  const selectedCount = allSelected ? allIds.length : [...selected].filter((id) => allIds.includes(id)).length

  useEffect(() => {
    if (!open) return
    function onDoc(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  function commit(next: Set<string>) {
    const ids = allIds.filter((id) => next.has(id))
    if (!ids.length || ids.length === allIds.length) onChange('all')
    else onChange(ids.join(','))
  }

  function toggleAll() {
    if (allSelected) commit(new Set())
    else commit(new Set(allIds))
  }

  function toggleOne(id: string) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    commit(next)
  }

  const label = allSelected
    ? 'Платформа'
    : selectedCount === 1
      ? items.find((o) => selected.has(o.id))?.label || 'Платформа'
      : `Платформа · ${selectedCount}`

  return (
    <div className={`filter-dd${open ? ' is-open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className={`btn filter-dd__btn${allSelected ? '' : ' filter-dd__btn--active'}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{label}</span>
        <span className="filter-dd__chev" aria-hidden>
          ▾
        </span>
      </button>
      {open ? (
        <div className="filter-dd__menu" role="listbox" aria-multiselectable="true">
          <label className="filter-dd__option">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} />
            <span>Все</span>
          </label>
          <div className="filter-dd__sep" />
          {items.map((o) => (
            <label key={o.id} className="filter-dd__option">
              <input
                type="checkbox"
                checked={selected.has(o.id)}
                onChange={() => toggleOne(o.id)}
              />
              {o.color ? <span className="pill__dot" style={{ background: o.color }} /> : null}
              <span>{o.label}</span>
            </label>
          ))}
        </div>
      ) : null}
    </div>
  )
}

const PERIOD_OPTIONS = [
  { id: 'today', label: 'Сегодня' },
  { id: 'week', label: 'Неделя' },
  { id: 'all', label: 'Всё время' },
] as const

export function PeriodFilter({
  value,
  onChange,
}: {
  value: string
  onChange: (next: string) => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const current = PERIOD_OPTIONS.find((o) => o.id === value) || PERIOD_OPTIONS[2]

  useEffect(() => {
    if (!open) return
    function onDoc(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className={`filter-dd${open ? ' is-open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className="btn filter-dd__btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{current.label}</span>
        <span className="filter-dd__chev" aria-hidden>
          ▾
        </span>
      </button>
      {open ? (
        <div className="filter-dd__menu" role="listbox">
          {PERIOD_OPTIONS.map((o) => (
            <button
              key={o.id}
              type="button"
              role="option"
              aria-selected={o.id === current.id}
              className={`filter-dd__option filter-dd__option--btn${o.id === current.id ? ' is-active' : ''}`}
              onClick={() => {
                onChange(o.id)
                setOpen(false)
              }}
            >
              {o.label}
            </button>
          ))}
        </div>
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
