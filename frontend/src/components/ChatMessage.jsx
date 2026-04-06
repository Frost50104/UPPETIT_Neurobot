import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { submitFeedback, removeFeedback } from '../api/feedback'

export default function ChatMessage({ message }) {
  const isUser = message.role === 'user'
  const [lightbox, setLightbox] = useState(null)
  const [feedback, setFeedback] = useState(message.feedback || null)
  const [sending, setSending] = useState(false)

  const handleFeedback = async (type) => {
    if (sending) return
    setSending(true)
    try {
      if (feedback === type) {
        await removeFeedback(message.id)
        setFeedback(null)
      } else {
        await submitFeedback(message.id, type)
        setFeedback(type)
      }
    } catch (e) {
      console.error('Feedback error:', e)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className={`chat-message ${isUser ? 'user' : 'assistant'}`}>
      <div className={`chat-bubble ${isUser ? 'chat-bubble-user' : 'chat-bubble-assistant'}`}>
        {isUser ? (
          <p>{message.content}</p>
        ) : (
          <div className="markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}

        {/* Images from KB */}
        {message.images?.length > 0 && (
          <div className="chat-images">
            {message.images.map((img, i) => (
              <img
                key={i}
                src={`/api/kb-images/${img}`}
                alt=""
                className="chat-kb-image"
                onClick={() => setLightbox(`/api/kb-images/${img}`)}
              />
            ))}
          </div>
        )}

        {/* Like / Dislike buttons for assistant messages */}
        {!isUser && message.id && (
          <div className="feedback-buttons">
            <button
              className={`feedback-btn${feedback === 'like' ? ' active' : ''}`}
              onClick={() => handleFeedback('like')}
              disabled={sending}
              title="Полезный отв��т"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M7 10v12" />
                <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z" />
              </svg>
            </button>
            <button
              className={`feedback-btn${feedback === 'dislike' ? ' active' : ''}`}
              onClick={() => handleFeedback('dislike')}
              disabled={sending}
              title="Неточный ответ"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 14V2" />
                <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22h0a3.13 3.13 0 0 1-3-3.88Z" />
              </svg>
            </button>
          </div>
        )}
      </div>

      {/* Lightbox modal */}
      {lightbox && (
        <div className="lightbox-overlay" onClick={() => setLightbox(null)}>
          <button className="lightbox-close" onClick={() => setLightbox(null)}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
          <img
            src={lightbox}
            alt=""
            className="lightbox-image"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  )
}
