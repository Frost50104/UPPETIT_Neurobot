import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          position: 'fixed', inset: 0,
          background: 'var(--bg, #f8f9fa)',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          padding: '2rem', textAlign: 'center',
        }}>
          <div style={{ fontSize: '3rem', marginBottom: '1.5rem' }}>:(</div>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, marginBottom: '.75rem' }}>
            Произошла ошибка
          </h2>
          <p style={{ color: '#6B7280', lineHeight: 1.6, maxWidth: 300, marginBottom: '2rem' }}>
            Попробуйте перезагрузить приложение
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              background: '#F37021', color: '#fff', border: 'none',
              padding: '.75rem 2rem', borderRadius: 8, fontSize: '1rem',
              fontWeight: 500, cursor: 'pointer',
            }}
          >
            Перезагрузить
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
