import { useState, useEffect } from 'react'

export default function IOSInstallBanner() {
  const [show, setShow] = useState(false)

  useEffect(() => {
    const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent)
    const isStandalone = window.navigator.standalone === true
    const dismissed = sessionStorage.getItem('ios-banner-dismissed')
    if (isIOS && !isStandalone && !dismissed) setShow(true)
  }, [])

  if (!show) return null

  const dismiss = () => {
    sessionStorage.setItem('ios-banner-dismissed', '1')
    setShow(false)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0,
      background: 'var(--primary)', color: '#fff',
      zIndex: 1000,
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: '2rem 1.5rem',
      paddingTop: 'calc(2rem + env(safe-area-inset-top))',
      paddingBottom: 'calc(2rem + env(safe-area-inset-bottom))',
    }}>
      {/* Close */}
      <button
        onClick={dismiss}
        style={{
          position: 'absolute', top: 'calc(1rem + env(safe-area-inset-top))', right: '1rem',
          background: 'rgba(255,255,255,.15)', color: '#fff',
          width: '2.2rem', height: '2.2rem', borderRadius: '50%',
          fontSize: '1.1rem', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >&times;</button>

      {/* Icon */}
      <img src="/icons/icon-192.png" alt="UPPETIT" style={{ width: 96, height: 96, borderRadius: 22, marginBottom: '2rem', boxShadow: '0 8px 24px rgba(0,0,0,.3)' }} />

      <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '.75rem', textAlign: 'center' }}>
        Установите приложение
      </h1>

      <p style={{ fontSize: '1rem', opacity: .85, lineHeight: 1.6, textAlign: 'center', maxWidth: 320, marginBottom: '3rem' }}>
        Добавьте приложение на экран «Домой» для удобного доступа к базе знаний
      </p>

      {/* Steps */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', width: '100%', maxWidth: 320 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', background: 'rgba(255,255,255,.1)', borderRadius: 'var(--radius)', padding: '1rem' }}>
          <span style={{ fontSize: '1.8rem', flexShrink: 0 }}>&#x238B;</span>
          <span style={{ fontSize: '.95rem', lineHeight: 1.4 }}>Нажмите кнопку <strong>«Поделиться»</strong> в Safari</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', background: 'rgba(255,255,255,.1)', borderRadius: 'var(--radius)', padding: '1rem' }}>
          <span style={{ fontSize: '1.8rem', flexShrink: 0 }}>&#xFF0B;</span>
          <span style={{ fontSize: '.95rem', lineHeight: 1.4 }}>Выберите <strong>«На экран "Домой"»</strong></span>
        </div>
      </div>

      <button
        onClick={dismiss}
        style={{
          marginTop: '3rem', width: '100%', maxWidth: 320,
          padding: '1rem', borderRadius: 'var(--radius)',
          background: 'rgba(255,255,255,.15)', color: '#fff',
          fontSize: '1rem', fontWeight: 500,
          border: '1.5px solid rgba(255,255,255,.3)',
        }}
      >
        Не сейчас
      </button>
    </div>
  )
}
