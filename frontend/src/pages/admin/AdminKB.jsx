import { useState, useEffect } from 'react'
import { getKBStatus, refreshKB, getKBHistory, deleteKBHistory, startBenchmark, getBenchmarkStatus, getFeedbackStats } from '../../api/admin'
import toast from 'react-hot-toast'

export default function AdminKB() {
  const [status, setStatus] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  // Benchmark state — new format: running (current) + benchHistory (last 3)
  const [benchRunningData, setBenchRunningData] = useState(null)
  const [benchHistory, setBenchHistory] = useState([])
  const [benchPolling, setBenchPolling] = useState(false)
  const [reportOpen, setReportOpen] = useState(null) // index into benchHistory, or 'running'

  // Feedback state
  const [fbStats, setFbStats] = useState(null)
  const [fbTab, setFbTab] = useState('dislikes') // 'dislikes' or 'likes'
  const [fbExpanded, setFbExpanded] = useState(null) // index of expanded item

  const load = async () => {
    try {
      const [statusRes, historyRes, benchRes, fbRes] = await Promise.all([
        getKBStatus(), getKBHistory(), getBenchmarkStatus(), getFeedbackStats(),
      ])
      setStatus(statusRes.data)
      setHistory(historyRes.data)
      setBenchRunningData(benchRes.data.running)
      setBenchHistory(benchRes.data.history || [])
      setFbStats(fbRes.data)
      if (benchRes.data.running?.status === 'running') setBenchPolling(true)
      if (statusRes.data.last_sync_status === 'in_progress') setRefreshing(true)
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  // Poll while refresh is in progress
  useEffect(() => {
    if (!refreshing) return
    const interval = setInterval(async () => {
      try {
        const [statusRes, historyRes] = await Promise.all([getKBStatus(), getKBHistory()])
        setStatus(statusRes.data)
        setHistory(historyRes.data)
        if (statusRes.data.last_sync_status !== 'in_progress') {
          setRefreshing(false)
          if (statusRes.data.last_sync_status === 'success') {
            toast.success('База знаний обновлена')
          } else {
            toast.error('Ошибка обновления базы знаний')
          }
        }
      } catch {}
    }, 3000)
    return () => clearInterval(interval)
  }, [refreshing])

  // Poll while benchmark is running
  useEffect(() => {
    if (!benchPolling) return
    const interval = setInterval(async () => {
      try {
        const res = await getBenchmarkStatus()
        const running = res.data.running
        setBenchRunningData(running)
        setBenchHistory(res.data.history || [])
        if (!running || running.status !== 'running') {
          setBenchPolling(false)
          if (!running && res.data.history?.[0]?.status === 'done') {
            const pct = res.data.history[0].summary?.overall_pct
            toast.success(`Бенчмарк завершён: ${pct}%`)
          } else if (running?.status === 'done') {
            toast.success(`Бенчмарк завершён: ${running.summary?.overall_pct}%`)
          } else if (running?.status === 'failed' || (!running && res.data.history?.[0]?.status === 'failed')) {
            toast.error('Ошибка бенчмарка')
          }
        }
      } catch {}
    }, 5000)
    return () => clearInterval(interval)
  }, [benchPolling])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await refreshKB()
      toast('Обновление запущено...')
      load()
    } catch (err) {
      setRefreshing(false)
      toast.error(err.response?.data?.detail || 'Ошибка')
    }
  }

  const handleBenchmark = async () => {
    setBenchPolling(true)
    try {
      await startBenchmark()
      toast('Бенчмарк запущен...')
      const res = await getBenchmarkStatus()
      setBenchRunningData(res.data.running)
      setBenchHistory(res.data.history || [])
    } catch (err) {
      setBenchPolling(false)
      toast.error(err.response?.data?.detail || 'Ошибка')
    }
  }

  const formatDate = (d) => {
    if (!d) return '—'
    return new Date(d).toLocaleString('ru-RU')
  }

  if (loading) return <div className="spinner" style={{ marginTop: '2rem' }} />

  const isRunning = benchRunningData?.status === 'running'
  const noBenchData = !isRunning && benchHistory.length === 0

  // Report content for modal
  const reportContent = reportOpen !== null
    ? (reportOpen === 'running' ? benchRunningData?.qa_report : benchHistory[reportOpen]?.qa_report)
    : null

  return (
    <div className="admin-page">
      <h2 style={{ marginBottom: '1rem' }}>База знаний</h2>

      <div className="card" style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '.75rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '.5rem', marginBottom: '.5rem' }}>
              <div style={{
                width: 10, height: 10, borderRadius: '50%',
                background: status?.is_ready ? 'var(--success)' : 'var(--danger)',
              }} />
              <strong>{status?.is_ready ? 'Активна' : 'Не загружена'}</strong>
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '.875rem' }}>
              Чанков: {status?.chunk_count || 0}
            </p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '.875rem' }}>
              Последнее обновление: {formatDate(status?.last_sync)}
            </p>
          </div>
          <button
            className="btn btn-primary"
            style={{ width: 'auto' }}
            onClick={handleRefresh}
            disabled={refreshing}
          >
            {refreshing ? 'Обновление...' : 'Обновить с Google Drive'}
          </button>
        </div>
      </div>

      {/* Benchmark section */}
      <h3 style={{ marginBottom: '.75rem' }}>Бенчмарк</h3>

      {/* Running benchmark */}
      {isRunning && (
        <div className="card" style={{ marginBottom: '.75rem' }}>
          {benchRunningData.total > 0 ? (() => {
            const pct = Math.round((benchRunningData.progress / benchRunningData.total) * 100)
            return (
              <div style={{ textAlign: 'center', padding: '.5rem 0' }}>
                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--accent)' }}>{pct}%</div>
                <p style={{ fontSize: '.85rem', color: 'var(--text-secondary)', margin: '.25rem 0 .75rem' }}>
                  Вопрос {benchRunningData.progress} из {benchRunningData.total}
                </p>
                <div style={{
                  height: 6, borderRadius: 3,
                  background: 'var(--border)', overflow: 'hidden',
                }}>
                  <div style={{
                    height: '100%', borderRadius: 3,
                    background: 'var(--accent)',
                    width: `${pct}%`,
                    transition: 'width .5s ease',
                  }} />
                </div>
              </div>
            )
          })() : (
            <div style={{ textAlign: 'center', padding: '.5rem 0' }}>
              <div className="spinner" style={{ width: 20, height: 20, margin: '0 auto .5rem' }} />
              <p style={{ fontSize: '.85rem', color: 'var(--text-secondary)' }}>Запуск...</p>
            </div>
          )}
        </div>
      )}

      {/* Idle state — show only when no running and no history */}
      {noBenchData && (
        <div className="card" style={{ marginBottom: '.75rem' }}>
          <div style={{ textAlign: 'center', padding: '.25rem 0' }}>
            <p style={{ color: 'var(--text-secondary)', fontSize: '.85rem', marginBottom: '.75rem' }}>
              Оценка качества ответов бота
            </p>
            <button
              className="btn btn-primary"
              onClick={handleBenchmark}
              disabled={refreshing}
            >
              Запустить бенчмарк
            </button>
          </div>
        </div>
      )}

      {/* Benchmark history cards */}
      {benchHistory.map((run, idx) => (
        <BenchCard
          key={run.started_at || idx}
          run={run}
          idx={idx}
          total={benchHistory.length}
          formatDate={formatDate}
          onReport={() => setReportOpen(idx)}
          onRestart={handleBenchmark}
          disabled={refreshing || isRunning}
        />
      ))}

      {/* Restart button if there is history but not running */}
      {benchHistory.length > 0 && !isRunning && (
        <div style={{ marginBottom: '1rem' }}>
          <button
            className="btn btn-primary"
            onClick={handleBenchmark}
            disabled={refreshing}
            style={{ width: '100%' }}
          >
            Запустить бенчмарк
          </button>
        </div>
      )}

      {/* Q&A Report modal */}
      {reportContent && (
        <div className="lightbox-overlay" onClick={() => setReportOpen(null)}>
          <div className="benchmark-report-modal" onClick={(e) => e.stopPropagation()}>
            <div className="benchmark-report-header">
              <strong>Отчёт бенчмарка</strong>
              <button className="lightbox-close" style={{ position: 'static' }} onClick={() => setReportOpen(null)}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <pre className="benchmark-report-body">{reportContent}</pre>
          </div>
        </div>
      )}

      {/* Feedback section */}
      <h3 style={{ marginBottom: '.75rem' }}>Обратная связь</h3>
      {fbStats && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '.75rem' }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--success)' }}>
                {fbStats.total_likes}
              </div>
              <div style={{ fontSize: '.8rem', color: 'var(--text-secondary)' }}>Лайков</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--danger)' }}>
                {fbStats.total_dislikes}
              </div>
              <div style={{ fontSize: '.8rem', color: 'var(--text-secondary)' }}>Дизлайков</div>
            </div>
          </div>

          {(fbStats.total_likes > 0 || fbStats.total_dislikes > 0) && (<>
            <div style={{ display: 'flex', gap: '.25rem', marginBottom: '.75rem' }}>
              <button
                className={`btn btn-sm${fbTab === 'dislikes' ? ' btn-primary' : ''}`}
                style={{ flex: 1, fontSize: '.8rem', padding: '.375rem .5rem' }}
                onClick={() => { setFbTab('dislikes'); setFbExpanded(null) }}
              >
                Дизлайки ({fbStats.total_dislikes})
              </button>
              <button
                className={`btn btn-sm${fbTab === 'likes' ? ' btn-primary' : ''}`}
                style={{ flex: 1, fontSize: '.8rem', padding: '.375rem .5rem' }}
                onClick={() => { setFbTab('likes'); setFbExpanded(null) }}
              >
                Лайки ({fbStats.total_likes})
              </button>
            </div>

            <div style={{ maxHeight: 400, overflowY: 'auto' }}>
              {(fbTab === 'dislikes' ? fbStats.recent_dislikes : fbStats.recent_likes).map((item, i) => (
                <div
                  key={i}
                  style={{
                    padding: '.5rem .625rem',
                    borderRadius: 8,
                    background: 'var(--bg)',
                    marginBottom: '.375rem',
                    cursor: 'pointer',
                    fontSize: '.85rem',
                  }}
                  onClick={() => setFbExpanded(fbExpanded === i ? null : i)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '.5rem' }}>
                    <div style={{ fontWeight: 500, flex: 1, minWidth: 0 }}>
                      <span style={{ color: fbTab === 'dislikes' ? 'var(--danger)' : 'var(--success)', marginRight: '.375rem' }}>
                        {fbTab === 'dislikes' ? '−' : '+'}
                      </span>
                      {item.question}
                    </div>
                    <span style={{ fontSize: '.75rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap', flexShrink: 0 }}>
                      {item.user}
                    </span>
                  </div>
                  {fbExpanded === i && (
                    <div style={{
                      marginTop: '.5rem', padding: '.5rem',
                      background: 'var(--surface)', borderRadius: 6,
                      fontSize: '.8rem', lineHeight: 1.5,
                      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    }}>
                      {item.answer}
                    </div>
                  )}
                  <div style={{ fontSize: '.7rem', color: 'var(--text-secondary)', marginTop: '.25rem' }}>
                    {formatDate(item.created_at)}
                  </div>
                </div>
              ))}
              {(fbTab === 'dislikes' ? fbStats.recent_dislikes : fbStats.recent_likes).length === 0 && (
                <p style={{ color: 'var(--text-secondary)', fontSize: '.85rem', textAlign: 'center', padding: '.5rem' }}>
                  Нет записей
                </p>
              )}
            </div>
          </>)}

          {fbStats.total_likes === 0 && fbStats.total_dislikes === 0 && (
            <p style={{ color: 'var(--text-secondary)', fontSize: '.85rem' }}>
              Пока нет оценок от пользователей
            </p>
          )}
        </div>
      )}

      <h3 style={{ marginBottom: '.75rem' }}>История обновлений</h3>
      {history.length === 0 ? (
        <p style={{ color: 'var(--text-secondary)' }}>Обновлений пока не было</p>
      ) : (
        <div className="admin-list">
          {history.map(log => (
            <div key={log.id} className="card" style={{ marginBottom: '.5rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '.5rem' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span className={`badge badge-kb-${log.status}`}>
                    {log.status === 'success' ? 'Успешно' : log.status === 'failed' ? 'Ошибка' : 'В процессе'}
                  </span>
                  <p style={{ fontSize: '.85rem', color: 'var(--text-secondary)', marginTop: '.25rem' }}>
                    {formatDate(log.started_at)}
                    {log.triggered_by_name && ` — ${log.triggered_by_name}`}
                  </p>
                  {log.status === 'success' && (
                    <p style={{ fontSize: '.85rem', marginTop: '.25rem' }}>
                      Файлов: {log.files_count}, чанков: {log.chunks_count}
                    </p>
                  )}
                  {log.error_message && (
                    <p style={{ fontSize: '.85rem', color: 'var(--danger)', marginTop: '.25rem' }}>
                      {log.error_message}
                    </p>
                  )}
                </div>
                <button
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: 'var(--text-secondary)', flexShrink: 0, padding: '.25rem',
                    borderRadius: 6, lineHeight: 0,
                  }}
                  onClick={async () => {
                    try {
                      await deleteKBHistory(log.id)
                      setHistory(prev => prev.filter(l => l.id !== log.id))
                    } catch {}
                  }}
                  title="Удалить"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


function BenchCard({ run, idx, total, formatDate, onReport, disabled }) {
  const s = run.summary
  const att = s?.attestation
  const isMostRecent = idx === 0

  if (run.status === 'failed') {
    return (
      <div className="card" style={{ marginBottom: '.75rem', opacity: isMostRecent ? 1 : 0.7 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <p style={{ color: 'var(--danger)', fontWeight: 600, marginBottom: '.25rem' }}>Ошибка</p>
            {run.error && (
              <p style={{ fontSize: '.8rem', color: 'var(--text-secondary)' }}>{run.error}</p>
            )}
          </div>
          <span style={{ fontSize: '.75rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
            {formatDate(run.finished_at)}
          </span>
        </div>
      </div>
    )
  }

  if (run.status !== 'done' || !s) return null

  return (
    <div className="card" style={{ marginBottom: '.75rem', opacity: isMostRecent ? 1 : 0.7 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '.5rem' }}>
          <span style={{
            fontSize: isMostRecent ? '1.75rem' : '1.25rem', fontWeight: 700,
            color: s.overall_pct >= 85 ? 'var(--success)' : s.overall_pct >= 70 ? 'var(--orange)' : 'var(--danger)',
          }}>
            {s.overall_pct}%
          </span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '.85rem' }}>
            {s.total_questions} вопросов
          </span>
        </div>
        <span style={{ fontSize: '.75rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
          {formatDate(run.finished_at)}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '.4rem' }}>
        <BenchStat label="Поиск" value={`${s.retrieval.hits}/${s.retrieval.total}`} pct={s.retrieval.rate_pct} />
        <BenchStat label="Точность фактов" value={`${s.fact_recall.hits}/${s.fact_recall.total}`} pct={s.fact_recall.rate_pct} />
        <BenchStat label="Оценка судьи" value={`${s.judge_avg.mean}/5`} pct={Math.round(s.judge_avg.mean * 20)} />
        {att && att.total > 0 && (
          <BenchStat label="Аттестация" value={`${att.correct}/${att.total}`} pct={att.accuracy_pct} />
        )}
      </div>

      {run.qa_report && (
        <button
          className="btn"
          style={{ width: '100%', marginTop: '.75rem' }}
          onClick={onReport}
        >
          Отчёт
        </button>
      )}
    </div>
  )
}


function BenchStat({ label, value, pct }) {
  const color = pct >= 85 ? 'var(--success)' : pct >= 70 ? 'var(--orange)' : 'var(--danger)'
  return (
    <div style={{
      padding: '.5rem .75rem', borderRadius: 8,
      background: 'var(--bg)', fontSize: '.85rem',
    }}>
      <div style={{ color: 'var(--text-secondary)', marginBottom: '.2rem' }}>{label}</div>
      <div style={{ fontWeight: 600 }}>
        {value} <span style={{ color, fontWeight: 700 }}>({pct}%)</span>
      </div>
    </div>
  )
}
