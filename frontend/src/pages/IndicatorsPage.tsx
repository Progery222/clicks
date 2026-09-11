import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError, type Indicators } from '../api'
import { BarChart, Modal } from '../components'

export function IndicatorsPage() {
  const [sp, setSp] = useSearchParams()
  const platform = sp.get('platform') || 'all'
  const preset = sp.get('preset') || 'all'
  const [data, setData] = useState<Indicators | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      const q = new URLSearchParams()
      if (platform !== 'all') q.set('platform', platform)
      if (preset !== 'all') q.set('preset', preset)
      const res = await api<Indicators>(`/admin/api/indicators?${q}`)
      setData(res)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка')
    }
  }, [platform, preset])

  useEffect(() => {
    void load()
  }, [load])

  function setFilter(next: Record<string, string>) {
    const merged = { platform, preset, ...next }
    const n = new URLSearchParams()
    if (merged.platform !== 'all') n.set('platform', merged.platform)
    if (merged.preset !== 'all') n.set('preset', merged.preset)
    setSp(n, { replace: true })
  }

  const exportQs = (() => {
    const n = new URLSearchParams()
    if (platform !== 'all') n.set('platform', platform)
    if (preset !== 'all') n.set('preset', preset)
    const s = n.toString()
    return s ? `?${s}` : ''
  })()

  if (error) return <div className="error-box">{error}</div>
  if (!data) return <div className="loading">Загрузка…</div>

  return (
    <div>
      <div className="row between wrap" style={{ gap: '1rem', alignItems: 'flex-start' }}>
        <div>
          <h1 className="page-title">Показатели</h1>
          <p className="muted small">Сводная аналитика по выбранным фильтрам · {data.period_label}</p>
        </div>
        <div className="admin-actions">
          <button type="button" className="btn" onClick={() => setImportOpen(true)}>
            Импорт CSV
          </button>
          <a className="btn" href={`/admin/export/links.csv${exportQs}`}>
            Ссылки CSV
          </a>
          <a className="btn" href={`/admin/export/clicks.csv${exportQs}`}>
            Клики CSV
          </a>
        </div>
      </div>

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
            <span className="kpi-card__lbl">кликов</span>
          </div>
          <div className="kpi-card kpi-card--accent">
            <span className="kpi-card__num">{data.period_uniques}</span>
            <span className="kpi-card__lbl">уникальных</span>
          </div>
        </div>

        {data.platform_stats?.length ? (
          <>
            <h2 className="section-title">Платформы за период</h2>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Платформа</th>
                    <th className="num">Клики</th>
                    <th className="num">Уник.</th>
                  </tr>
                </thead>
                <tbody>
                  {data.platform_stats.map((ps) => (
                    <tr key={ps.platform} style={{ cursor: 'default' }}>
                      <td>
                        <span className="row" style={{ gap: '0.4rem' }}>
                          <span className="pill__dot" style={{ background: ps.color }} />
                          {ps.label}
                        </span>
                      </td>
                      <td className="num">{ps.clicks}</td>
                      <td className="num">{ps.uniques}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}

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
              Платформы
            </h2>
            <BarChart items={data.charts.platforms} limit={5} />
          </div>
        </div>
      </div>

      <ImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onDone={() => setImportOpen(false)}
      />
    </div>
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
