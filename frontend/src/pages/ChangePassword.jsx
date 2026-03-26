import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { changePassword } from '../api/auth'
import { useAuthStore } from '../store/auth'
import toast from 'react-hot-toast'

export default function ChangePassword() {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' })
  const [loading, setLoading] = useState(false)
  const { setUser, user } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (form.next !== form.confirm) { toast.error('Пароли не совпадают'); return }
    if (form.next.length < 8) { toast.error('Минимум 8 символов'); return }
    setLoading(true)
    try {
      await changePassword(form.current, form.next)
      setUser({ ...user, must_change_password: false })
      toast.success('Пароль успешно изменён')
      navigate('/')
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fullscreen-page" style={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem', background: 'var(--primary)' }}>
      <div style={{ width: '100%', maxWidth: 400 }}>
        <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
          <div style={{ fontSize: '2.5rem', color: 'var(--accent)' }}>
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
            </svg>
          </div>
          <h2 style={{ color: '#fff', marginTop: '.5rem' }}>Смена пароля</h2>
          <p style={{ color: 'rgba(255,255,255,.7)', fontSize: '.85rem' }}>
            Для продолжения необходимо сменить пароль
          </p>
        </div>
        <form onSubmit={handleSubmit} style={{
          background: 'var(--surface)', borderRadius: 'var(--radius)',
          padding: '2rem', display: 'flex', flexDirection: 'column', gap: '1.25rem',
        }}>
          <div className="form-group">
            <label>Текущий пароль</label>
            <input type="password" value={form.current}
              onChange={e => setForm(f => ({ ...f, current: e.target.value }))} required />
          </div>
          <div className="form-group">
            <label>Новый пароль</label>
            <input type="password" placeholder="Минимум 8 символов" value={form.next}
              onChange={e => setForm(f => ({ ...f, next: e.target.value }))} required />
          </div>
          <div className="form-group">
            <label>Повторите новый пароль</label>
            <input type="password" value={form.confirm}
              onChange={e => setForm(f => ({ ...f, confirm: e.target.value }))} required />
          </div>
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Сохранение...' : 'Сохранить'}
          </button>
        </form>
      </div>
    </div>
  )
}
