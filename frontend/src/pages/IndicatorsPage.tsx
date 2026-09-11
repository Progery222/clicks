import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError, type Indicators } from '../api'
import { BarChart } from '../components'

export function IndicatorsPage() {
  const [sp, setSp] = useSearchParams()
  const profile = sp.get('profile') || 'all'
  const platform = sp.get('platform') || 'all'
  const preset = sp.get('preset') || 'all'
  const [data, setData] = useState<Indicators | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const q = new URLSearchParams()
      if (profile !== 'all') q.set('profile', profile)
      if (platform !== 'all') q.set('platform', platform)
      if (preset !== 'all') q.set('preset', preset)
      const res = await api<Indicators>(`/admin/api/indicators?${q}`)
      setData(res)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    }
  }, [profile, platform, preset])

  useEffect(() => {
    void load()
  }, [load])

  function setFilter(next: Record<string, string>) {
    const merged = { profile, platform, preset, ...next }
    const n = new URLSearchParams()
    if (merged.profile !== 'all') n.set('profile', merged.profile)
    if (merged.platform !== 'all') n.set('platform', merged.platform)
    if (merged.preset !== 'all') n.set('preset', merged.preset)
    setSp(n, { replace: true })
  }

  if (error) return <div className="error-box">{error}</div>
  if (!data) return <div className="loading">Загрузка…</div>

  return (
    <div>
      <h1 className="page-title">Показатели</h1>
      <p className="muted small">Сводная аналитика по выбранным фильтрам · {data.period_label}</p>

      <div className="links-layout">
        <aside className="sidebar stack">
          {data.profile_filters.map((pf) => (
            <button
              key={pf.id}
              type="button"
              className={`sidebar-item${profile === pf.id ? ' active' : ''}`}
              onClick={() => setFilter({ profile: pf.id })}
            >
              <span className="ring" style={{ background: pf.color || 'var(--muted)' }}>
                {pf.id === 'all' || pf.id === 'none' ? '' : pf.name.slice(0, 1)}
              </span>
              <span>{pf.name}</span>
              <span className="sidebar-item__count">{pf.count}</span>
            </button>
          ))}
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
              <span className="kpi-card__lbl">кликов</span>
            </div>
            <div className="kpi-card kpi-card--accent">
              <span className="kpi-card__num">{data.period_uniques}</span>
              <span className="kpi-card__lbl">уникальных</span>
            </div>
          </div>
          <div className="charts-grid">
            <div className="card">
              <h2 className="section-title" style={{ marginTop: 0 }}>
                ОС
              </h2>
              <BarChart items={data.charts.os} limit={5} />
            </div>
            <div className="card">
              <h2 className="section-title" style={{ marginTop: 0 }}>
                Устройства
              </h2>
              <BarChart items={data.charts.devices} limit={5} />
            </div>
            <div className="card">
              <h2 className="section-title" style={{ marginTop: 0 }}>
                Профили
              </h2>
              <BarChart items={data.charts.profiles} limit={5} />
            </div>
            <div className="card">
              <h2 className="section-title" style={{ marginTop: 0 }}>
                Платформы
              </h2>
              <BarChart items={data.charts.platforms} limit={5} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
