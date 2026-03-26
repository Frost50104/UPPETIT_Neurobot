import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { createChat, deleteChat, renameChat } from '../api/chats'
import { logout as apiLogout } from '../api/auth'
import { useAuthStore } from '../store/auth'
import api from '../api/client'

export default function ChatSidebar({ chats, activeId, onChatsChange, onClose }) {
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const [backendVersion, setBackendVersion] = useState('')
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()
  const isAdmin = user?.roles?.includes('admin')

  useEffect(() => {
    api.get('/env')
      .then(({ data }) => setBackendVersion(data.backend || ''))
      .catch(() => {})
  }, [])

  const handleNew = async () => {
    try {
      const { data } = await createChat()
      onChatsChange()
      navigate(`/chat/${data.id}`)
      onClose?.()
    } catch {}
  }

  const handleDelete = async (e, id) => {
    e.stopPropagation()
    if (!confirm('Удалить чат?')) return
    try {
      await deleteChat(id)
      onChatsChange()
      if (activeId === id) navigate('/')
    } catch {}
  }

  const handleRename = async (id) => {
    if (!editTitle.trim()) { setEditingId(null); return }
    try {
      await renameChat(id, editTitle.trim())
      onChatsChange()
    } catch {}
    setEditingId(null)
  }

  const handleLogout = async () => {
    try { await apiLogout() } catch {}
    logout()
    navigate('/login')
  }

  return (
    <div className="chat-sidebar">
      <div className="sidebar-header">
        <p className="sidebar-greeting">Привет, {user?.full_name}</p>
        <button className="btn btn-primary sidebar-new-btn" onClick={handleNew}>
          + Новый чат
        </button>
      </div>

      <div className="sidebar-chats">
        {chats.map(chat => (
          <div
            key={chat.id}
            className={`sidebar-chat-item ${chat.id === activeId ? 'active' : ''}`}
            onClick={() => { navigate(`/chat/${chat.id}`); onClose?.() }}
          >
            {editingId === chat.id ? (
              <input
                className="sidebar-edit-input"
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
                onBlur={() => handleRename(chat.id)}
                onKeyDown={e => { if (e.key === 'Enter') handleRename(chat.id); if (e.key === 'Escape') setEditingId(null) }}
                onClick={e => e.stopPropagation()}
                autoFocus
              />
            ) : (
              <>
                <span className="sidebar-chat-title">{chat.title}</span>
                <div className="sidebar-chat-actions">
                  <button
                    className="sidebar-action-btn"
                    onClick={(e) => { e.stopPropagation(); setEditingId(chat.id); setEditTitle(chat.title) }}
                    title="Переименовать"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 3a2.85 2.85 0 114 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                  </button>
                  <button
                    className="sidebar-action-btn danger"
                    onClick={(e) => handleDelete(e, chat.id)}
                    title="Удалить"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
        {chats.length === 0 && (
          <div className="sidebar-empty">Нет чатов</div>
        )}
      </div>

      <div className="sidebar-footer">
        {isAdmin && (
          <div className="sidebar-admin-links">
            <button className="sidebar-link" onClick={() => { navigate('/admin/users'); onClose?.() }}>
              Пользователи
            </button>
            <button className="sidebar-link" onClick={() => { navigate('/admin/kb'); onClose?.() }}>
              База знаний
            </button>
          </div>
        )}
        <div style={{ textAlign: 'center', fontSize: '.7rem', color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: '.5rem' }}>
          <div>Frontend: {typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'dev'}</div>
          {backendVersion && <div>Backend: {backendVersion}</div>}
        </div>
        <button className="sidebar-link" onClick={handleLogout}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: '.5rem', flexShrink: 0 }}><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/></svg>
          Выйти
        </button>
      </div>
    </div>
  )
}
