import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api/auth'
import { useAuthStore } from '../store/auth'

export default function Login() {
  const [form, setForm] = useState({ username: '', password: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const { setUser } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await login(form.username.trim(), form.password)
      setUser(data)
      if (data.must_change_password) navigate('/change-password')
      else navigate('/')
    } catch (err) {
      setError(err.response?.data?.detail || 'Ошибка входа. Попробуйте ещё раз.')
    } finally {
      setLoading(false)
    }
  }

  const handleChange = (field) => (e) => {
    setError('')
    setForm(f => ({ ...f, [field]: e.target.value }))
  }

  return (
    <div className="fullscreen-page" style={{
      minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '1rem', background: 'var(--primary)',
    }}>
      <div style={{ width: '100%', maxWidth: '380px' }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '.5rem', color: 'var(--accent)' }}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M12 2a7 7 0 017 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 01-2 2h-4a2 2 0 01-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 017-7z"/>
              <path d="M9 21h6M10 17v4M14 17v4"/>
            </svg>
          </div>
          <h1 style={{ color: '#fff', fontSize: '1.5rem', fontWeight: 500, marginBottom: '.25rem' }}>
            UPPETIT
          </h1>
          <p style={{ color: 'rgba(255,255,255,.5)', fontSize: '.8rem', fontWeight: 300, letterSpacing: '.1em' }}>
            БАЗА ЗНАНИЙ
          </p>
        </div>

        <form onSubmit={handleSubmit} style={{
          background: 'var(--surface)', borderRadius: 'var(--radius)',
          padding: '2rem', display: 'flex', flexDirection: 'column', gap: '1.25rem',
          boxShadow: 'var(--shadow-lg)',
        }}>
          <div className="form-group">
            <label>Логин</label>
            <input
              type="text"
              placeholder="username"
              value={form.username}
              onChange={handleChange('username')}
              autoComplete="username"
              style={error ? { borderColor: 'var(--danger)' } : {}}
              required
            />
          </div>
          <div className="form-group">
            <label>Пароль</label>
            <div style={{ position: 'relative' }}>
              <input
                type={showPassword ? 'text' : 'password'}
                placeholder="********"
                value={form.password}
                onChange={handleChange('password')}
                autoComplete="current-password"
                style={{ paddingRight: '2.75rem', ...(error ? { borderColor: 'var(--danger)' } : {}) }}
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword(v => !v)}
                style={{
                  position: 'absolute', right: '0.75rem', top: '50%', transform: 'translateY(-50%)',
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--text-secondary)', fontSize: '1.1rem', padding: '0.25rem',
                }}
              >
                {showPassword ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
                    <line x1="1" y1="1" x2="23" y2="23"/>
                  </svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                    <circle cx="12" cy="12" r="3"/>
                  </svg>
                )}
              </button>
            </div>
          </div>

          {error && (
            <div style={{
              background: '#fef2f2', border: '1px solid #fecaca',
              borderRadius: 8, padding: '.75rem 1rem',
              color: '#dc2626', fontSize: '.875rem', lineHeight: 1.4,
            }}>
              {error}
            </div>
          )}

          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Вход...' : 'Войти'}
          </button>
        </form>
      </div>
    </div>
  )
}
