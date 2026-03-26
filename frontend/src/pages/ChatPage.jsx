import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import ChatMessage from '../components/ChatMessage'
import ChatInput from '../components/ChatInput'
import { listMessages, askQuestion, getKbStatus } from '../api/messages'
import { createChat } from '../api/chats'

export default function ChatPage() {
  const { chatId } = useParams()
  const navigate = useNavigate()
  const { onChatsChange } = useOutletContext()
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [kbRebuilding, setKbRebuilding] = useState(false)
  const messagesContainerRef = useRef(null)
  const kbPollRef = useRef(null)
  const skipNextFetchRef = useRef(false)

  // Check KB status on mount
  useEffect(() => {
    getKbStatus().then(({ data }) => {
      if (data.rebuilding) { setKbRebuilding(true); startKbPoll() }
    }).catch(() => {})
    return () => { if (kbPollRef.current) clearInterval(kbPollRef.current) }
  }, [])

  const startKbPoll = () => {
    if (kbPollRef.current) return
    kbPollRef.current = setInterval(async () => {
      try {
        const { data } = await getKbStatus()
        if (!data.rebuilding) {
          setKbRebuilding(false)
          clearInterval(kbPollRef.current)
          kbPollRef.current = null
        }
      } catch {}
    }, 5000)
  }

  useEffect(() => {
    if (!chatId) {
      setMessages([])
      return
    }
    if (skipNextFetchRef.current) {
      skipNextFetchRef.current = false
      return
    }
    setLoading(true)
    listMessages(chatId)
      .then(({ data }) => setMessages(data))
      .catch(() => setMessages([]))
      .finally(() => setLoading(false))
  }, [chatId])

  useEffect(() => {
    requestAnimationFrame(() => {
      const el = messagesContainerRef.current
      if (el) el.scrollTop = el.scrollHeight
    })
  }, [messages, thinking])

  const handleSend = async (question) => {
    let targetChatId = chatId

    // Create chat if none selected
    if (!targetChatId) {
      try {
        const { data } = await createChat()
        targetChatId = data.id
        skipNextFetchRef.current = true
        navigate(`/chat/${targetChatId}`, { replace: true })
        onChatsChange()
      } catch {
        return
      }
    }

    // Optimistic user message
    const tempUserMsg = {
      id: Date.now(),
      chat_id: targetChatId,
      role: 'user',
      content: question,
      sources: [],
      images: [],
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, tempUserMsg])
    setThinking(true)

    try {
      const { data } = await askQuestion(targetChatId, question)
      // Replace temp user message and add assistant message
      setMessages(prev => [
        ...prev.filter(m => m.id !== tempUserMsg.id),
        data.user_message,
        data.assistant_message,
      ])
      onChatsChange()
    } catch (err) {
      if (err.response?.status === 503 && err.response?.data?.detail === 'kb_rebuilding') {
        setMessages(prev => prev.filter(m => m.id !== tempUserMsg.id))
        setKbRebuilding(true)
        startKbPoll()
        return
      }
      const errorMsg = {
        id: Date.now() + 1,
        chat_id: targetChatId,
        role: 'assistant',
        content: err.response?.data?.detail || 'Произошла ошибка при обработке вопроса. Попробуйте ещё раз.',
        sources: [],
        images: [],
        created_at: new Date().toISOString(),
      }
      setMessages(prev => [...prev, errorMsg])
    } finally {
      setThinking(false)
    }
  }

  if (!chatId && messages.length === 0) {
    return (
      <div className="chat-content">
        {kbRebuilding && <KbRebuildingBanner />}
        <div className="chat-welcome">
          <div className="welcome-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M12 2a7 7 0 017 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 01-2 2h-4a2 2 0 01-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 017-7z"/>
              <path d="M9 21h6M10 17v4M14 17v4"/>
            </svg>
          </div>
          <h2>UPPETIT Neurobot</h2>
          <p>Задайте вопрос по корпоративной базе знаний</p>
        </div>
        <ChatInput onSend={handleSend} disabled={thinking || kbRebuilding} />
      </div>
    )
  }

  return (
    <div className="chat-content">
      {kbRebuilding && <KbRebuildingBanner />}
      <div className="chat-messages" ref={messagesContainerRef}>
        {loading ? (
          <div className="spinner" />
        ) : (
          <>
            {messages.map(msg => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
            {thinking && (
              <div className="chat-message assistant">
                <div className="chat-bubble chat-bubble-assistant thinking">
                  <div className="thinking-dots">
                    <span /><span /><span />
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
      <ChatInput onSend={handleSend} disabled={thinking || kbRebuilding} />
    </div>
  )
}

function KbRebuildingBanner() {
  return (
    <div style={{
      background: 'var(--accent)', color: '#fff',
      fontSize: '.85rem', fontWeight: 500,
      padding: '.6rem 1rem', textAlign: 'center',
    }}>
      Идёт обновление базы знаний — отправка сообщений временно недоступна
    </div>
  )
}
