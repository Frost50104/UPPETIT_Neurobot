import { useState, useEffect } from 'react'
import { listUsers, createUser, updateUser, resetPassword, deleteUser } from '../../api/admin'
import toast from 'react-hot-toast'

export default function AdminUsers() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ username: '', full_name: '', password: '', role_name: 'employee' })

  const load = async () => {
    try {
      const { data } = await listUsers()
      setUsers(data)
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const handleCreate = async (e) => {
    e.preventDefault()
    try {
      await createUser(form)
      toast.success('Пользователь создан')
      setShowForm(false)
      setForm({ username: '', full_name: '', password: '', role_name: 'employee' })
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Ошибка')
    }
  }

  const handleResetPassword = async (userId, name) => {
    if (!confirm(`Сбросить пароль для ${name}?`)) return
    try {
      const { data } = await resetPassword(userId)
      toast.success(`Временный пароль: ${data.temp_password}`, { duration: 10000 })
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Ошибка')
    }
  }

  const handleDelete = async (userId, name) => {
    if (!confirm(`Удалить пользователя ${name}?`)) return
    try {
      await deleteUser(userId)
      toast.success('Пользователь удалён')
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Ошибка')
    }
  }

  const handleChangeRole = async (userId, newRole) => {
    try {
      await updateUser(userId, { role_name: newRole })
      toast.success('Роль изменена')
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Ошибка')
    }
  }

  return (
    <div className="admin-page">
      <div className="admin-header">
        <h2>Пользователи</h2>
        <button className="btn btn-primary" style={{ width: 'auto' }} onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Отмена' : '+ Создать'}
        </button>
      </div>

      {showForm && (
        <form className="card" onSubmit={handleCreate} style={{ marginBottom: '1rem', display: 'flex', flexDirection: 'column', gap: '.75rem' }}>
          <div className="form-group">
            <label>Логин</label>
            <input value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))} required />
          </div>
          <div className="form-group">
            <label>Имя</label>
            <input value={form.full_name} onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))} required />
          </div>
          <div className="form-group">
            <label>Пароль</label>
            <input type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} required minLength={8} />
          </div>
          <div className="form-group">
            <label>Роль</label>
            <select value={form.role_name} onChange={e => setForm(f => ({ ...f, role_name: e.target.value }))}>
              <option value="employee">Сотрудник</option>
              <option value="admin">Администратор</option>
            </select>
          </div>
          <button type="submit" className="btn btn-primary">Создать</button>
        </form>
      )}

      {loading ? <div className="spinner" /> : (
        <div className="admin-list">
          {users.map(u => (
            <div key={u.id} className="card admin-user-card">
              <div className="admin-user-info">
                <strong>{u.full_name}</strong>
                <span className="admin-user-meta">@{u.username} / {u.roles.join(', ')}</span>
              </div>
              <div className="admin-user-actions">
                <select
                  value={u.roles[0] || 'employee'}
                  onChange={e => handleChangeRole(u.id, e.target.value)}
                  style={{ width: 'auto', padding: '.25rem .5rem', fontSize: '.85rem' }}
                >
                  <option value="employee">Сотрудник</option>
                  <option value="admin">Администратор</option>
                </select>
                <button className="btn btn-secondary" style={{ padding: '.25rem .75rem', fontSize: '.85rem' }}
                  onClick={() => handleResetPassword(u.id, u.full_name)}>
                  Сбросить пароль
                </button>
                <button className="btn btn-danger" style={{ padding: '.25rem .75rem', fontSize: '.85rem' }}
                  onClick={() => handleDelete(u.id, u.full_name)}>
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
