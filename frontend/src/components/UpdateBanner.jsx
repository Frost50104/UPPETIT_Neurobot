import { useState, useEffect, useRef } from 'react'
import { useRegisterSW } from 'virtual:pwa-register/react'

const UPDATE_INTERVAL = 15 * 1000

export default function UpdateBanner() {
  const [updating, setUpdating] = useState(false)
  const intervalRef = useRef(null)

  const { needRefresh: [needRefresh], updateServiceWorker } = useRegisterSW({
    onRegisteredSW(swUrl, registration) {
      if (!registration) return
      const check = () => registration.update()
      const interval = setInterval(check, UPDATE_INTERVAL)
      const onVisibility = () => {
        if (document.visibilityState === 'visible') check()
      }
      const onFocus = () => check()
      document.addEventListener('visibilitychange', onVisibility)
      window.addEventListener('focus', onFocus)
      intervalRef.current = { interval, onVisibility, onFocus }
    },
  })

  useEffect(() => {
    return () => {
      if (!intervalRef.current) return
      clearInterval(intervalRef.current.interval)
      document.removeEventListener('visibilitychange', intervalRef.current.onVisibility)
      window.removeEventListener('focus', intervalRef.current.onFocus)
    }
  }, [])

  const handleUpdate = async () => {
    setUpdating(true)
    let ok = false
    try {
      await updateServiceWorker(true)
      ok = true
    } catch (e) {
      console.error('SW update error:', e)
      setUpdating(false)
    }
    if (ok) setTimeout(() => { window.location.reload() }, 1500)
  }

  if (!needRefresh) return null

  return (
    <div style={{
      position: 'fixed', bottom: 'calc(env(safe-area-inset-bottom) + 5rem)',
      left: '1rem', right: '1rem',
      background: '#111', color: '#fff',
      borderRadius: 'var(--radius)', padding: '.875rem 1rem',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem',
      boxShadow: '0 4px 24px rgba(0,0,0,.3)',
      zIndex: 200,
    }}>
      <span style={{ fontSize: '.9rem', fontWeight: 400 }}>
        Доступно обновление
      </span>
      <button
        onClick={handleUpdate}
        disabled={updating}
        style={{
          background: 'var(--accent)', color: '#fff',
          padding: '.4rem .9rem', borderRadius: 8,
          fontWeight: 600, fontSize: '.85rem', flexShrink: 0,
        }}
      >
        {updating ? '...' : 'Обновить'}
      </button>
    </div>
  )
}
