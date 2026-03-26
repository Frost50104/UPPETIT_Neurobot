import { useState, useEffect, useCallback, useRef } from 'react'
import { Outlet, useMatch } from 'react-router-dom'
import ChatSidebar from './ChatSidebar'
import UpdateBanner from './UpdateBanner'
import StagingBadge from './StagingBadge'
import { listChats } from '../api/chats'

export default function Layout() {
  const [chats, setChats] = useState([])
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const chatMatch = useMatch('/chat/:chatId')
  const activeId = chatMatch?.params?.chatId ? Number(chatMatch.params.chatId) : null
  const touchRef = useRef({ startX: 0, startY: 0 })
  const layoutRef = useRef(null)

  const loadChats = useCallback(async () => {
    try {
      const { data } = await listChats()
      setChats(data)
    } catch {}
  }, [])

  useEffect(() => { loadChats() }, [loadChats])

  // Swipe right from left edge → open sidebar (block browser back navigation)
  useEffect(() => {
    const el = layoutRef.current
    if (!el) return

    let edgeSwipe = false

    const onTouchStart = (e) => {
      const t = e.touches[0]
      touchRef.current = { startX: t.clientX, startY: t.clientY }
      // Detect touch starting near left edge — claim it to block browser back
      edgeSwipe = t.clientX < 40
    }

    const onTouchMove = (e) => {
      if (!edgeSwipe) return
      const t = e.touches[0]
      const dx = t.clientX - touchRef.current.startX
      const dy = Math.abs(t.clientY - touchRef.current.startY)
      // Horizontal swipe from left edge → prevent browser back gesture
      if (dx > 10 && dy < dx) {
        e.preventDefault()
      }
    }

    const onTouchEnd = (e) => {
      const t = e.changedTouches[0]
      const { startX, startY } = touchRef.current
      const dx = t.clientX - startX
      const dy = Math.abs(t.clientY - startY)

      // Right swipe from left edge → open sidebar
      if (dx > 60 && dy < dx * 0.5 && startX < 40 && !sidebarOpen) {
        setSidebarOpen(true)
      }
      // Left swipe when sidebar is open → close it
      if (dx < -60 && dy < Math.abs(dx) * 0.5 && sidebarOpen) {
        setSidebarOpen(false)
      }
      edgeSwipe = false
    }

    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: true })
    return () => {
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend', onTouchEnd)
    }
  }, [sidebarOpen])

  return (
    <div className="chat-layout" ref={layoutRef}>
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <div className={`sidebar-container ${sidebarOpen ? 'open' : ''}`}>
        <ChatSidebar
          chats={chats}
          activeId={activeId}
          onChatsChange={loadChats}
          onClose={() => setSidebarOpen(false)}
        />
      </div>

      {/* Main area */}
      <div className="chat-main">
        <div className="chat-header">
          <button className="hamburger-btn" onClick={() => setSidebarOpen(true)}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
          </button>
          <span className="chat-header-title">UPPETIT Neurobot</span>
          <StagingBadge />
        </div>
        <Outlet context={{ chats, onChatsChange: loadChats }} />
      </div>
      <UpdateBanner />
    </div>
  )
}
